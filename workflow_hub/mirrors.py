"""探测秋叶（绘世）启动器的镜像配置，为 Git 克隆与 pip 安装提供与启动器一致的下载来源。

启动器把开关写在 ``<整合包根>/.launcher/preference.json`` 的 ``network_preference``，
镜像清单写在同目录 ``data.json`` 的 ``mirrors``：

- ``mirror_git`` + ``git_mirrors``：已知仓库的 src→dest 重写表（LibGit2Sharp 克隆时应用，
  不设置 git insteadOf，因此子进程克隆必须自行重写）。
- ``mirror_pypi`` + ``pip_index``：带优先级的 PyPI 镜像列表，仅在启动器自己装包时生效。

非秋叶环境（找不到 ``.launcher``）返回空配置，所有调用方行为保持不变。
配置按文件 mtime 缓存，启动器里切换开关后无需重启 ComfyUI 即可生效。
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
import re
import sys
from typing import Any
from urllib.parse import urlparse

_GITHUB_REPO_RE = re.compile(r"github\.com[:/](?P<owner>[A-Za-z0-9_.-]+)/(?P<repo>[A-Za-z0-9_.-]+?)(?:\.git)?/?$", re.IGNORECASE)
_OWNER_REPO_RE = re.compile(r"^(?P<owner>[A-Za-z0-9_.-]+)/(?P<repo>[A-Za-z0-9_.-]+)$")
_PIP_PROBE_TIMEOUT = 3.0


def _github_owner_repo(value: str) -> tuple[str, str] | None:
    """从完整 GitHub 地址或启动器镜像表中的 owner/repo 简写提取归属。"""
    text = value.strip()
    match = _GITHUB_REPO_RE.search(text) or _OWNER_REPO_RE.fullmatch(text)
    if not match:
        return None
    return match.group("owner"), match.group("repo")


class LauncherMirrors:
    """一次解析结果；字段为空表示对应开关关闭或非秋叶环境。"""

    def __init__(
        self,
        *,
        mirror_git: bool = False,
        git_mirrors: list[dict[str, Any]] | None = None,
        mirror_pypi: bool = False,
        pip_index: list[dict[str, Any]] | None = None,
        pip_trusted_host: list[str] | None = None,
    ) -> None:
        self.mirror_git = mirror_git
        self.git_mirrors = git_mirrors or []
        self.mirror_pypi = mirror_pypi
        self.pip_index = pip_index or []
        self.pip_trusted_host = pip_trusted_host or []
        self._pip_selection: tuple[str, ...] | None = None

    @property
    def available(self) -> bool:
        return bool(self.mirror_git or self.mirror_pypi)

    def _git_mirror_dest(self, canonical_url: str) -> str | None:
        """在启动器 git_mirrors 表中查找 canonical GitHub 地址对应的镜像地址。"""
        if not self.mirror_git:
            return None
        for entry in self.git_mirrors:
            dest = str(entry.get("dest") or "").strip()
            if not dest:
                continue
            for src in entry.get("src") or []:
                if _same_repository(str(src), canonical_url):
                    return dest
        return None

    def git_clone_candidates(self, canonical_url: str) -> list[str]:
        """克隆/拉取候选地址：镜像优先（已知映射时），始终保留 canonical 兜底。"""
        candidates: list[str] = []
        mirror = self._git_mirror_dest(canonical_url)
        if mirror and mirror != canonical_url:
            candidates.append(mirror)
        candidates.append(canonical_url)
        return candidates

    def canonical_remote_url(self, remote_url: str) -> str | None:
        """把工作副本的 remote 地址归一化为 canonical ``https://github.com/owner/repo``。

        覆盖：原生 github.com（含 ssh）、启动器 git_mirrors 的 dest/src 别名、
        以及 ghproxy 一类的``前缀 + 完整 GitHub 地址``形式。
        """
        text = (remote_url or "").strip()
        if not text:
            return None
        match = _GITHUB_REPO_RE.search(text)
        if match:
            return f"https://github.com/{match.group('owner')}/{match.group('repo')}"
        # 镜像映射里的非 GitHub 地址（如 jihulab/gitee）按 src 中首个 GitHub 地址归一
        normalized = text[:-4] if text.endswith(".git") else text
        normalized = normalized.rstrip("/")
        for entry in self.git_mirrors:
            aliases = [str(entry.get("dest") or ""), *(str(item) for item in entry.get("src") or [])]
            for alias in aliases:
                alias = alias.strip()
                if not alias:
                    continue
                alias_normalized = (alias[:-4] if alias.endswith(".git") else alias).rstrip("/")
                if normalized.casefold() != alias_normalized.casefold():
                    continue
                for src in entry.get("src") or []:
                    src_repo = _github_owner_repo(str(src))
                    if src_repo:
                        return f"https://github.com/{src_repo[0]}/{src_repo[1]}"
        return None

    def pip_index_candidates(self) -> list[tuple[str, bool]]:
        """按优先级降序返回 (index_url, 是否内网地址)；开关关闭或清单为空时返回空列表。"""
        if not self.mirror_pypi:
            return []
        entries: list[tuple[int, str]] = []
        for item in self.pip_index:
            url = str(item.get("index_url") or "").strip()
            if not url:
                continue
            try:
                priority = int(item.get("priority") or 0)
            except (TypeError, ValueError):
                priority = 0
            entries.append((priority, url))
        entries.sort(key=lambda item: item[0], reverse=True)
        return [(url, _is_intranet_url(url)) for _priority, url in entries]

    async def select_pip_arguments(self) -> list[str]:
        """选出当前可用的 pip 镜像参数；全部不可达时回退为 pip 默认源（继承进程代理）。

        结果按进程缓存（同一配置 mtime 下只探测一次），内网地址排最后且仅在公网镜像
        全部不可达时参与探测，避免普通用户为阿里云内网域名白白等待 DNS 超时。
        """
        if self._pip_selection is not None:
            return list(self._pip_selection)
        candidates = self.pip_index_candidates()
        if not candidates:
            return []
        public = [url for url, intranet in candidates if not intranet]
        intranet = [url for url, intranet in candidates if intranet]
        reachable = await _first_reachable(public)
        if reachable is None:
            reachable = await _first_reachable(intranet)
        if reachable is None:
            self._pip_selection = ()
            return []
        arguments = ["--index-url", reachable]
        host = (urlparse(reachable).hostname or "").lower()
        if reachable.startswith("http://") or host in {item.lower() for item in self.pip_trusted_host}:
            arguments += ["--trusted-host", host]
        self._pip_selection = tuple(arguments)
        return list(arguments)


def _is_intranet_url(url: str) -> bool:
    """阿里云 VPC 内网域名只对云服务器可达，普通用户探测它只会白等超时。"""
    host = (urlparse(url).hostname or "").lower()
    return host.endswith(".aliyuncs.com")


def _same_repository(url_a: str, url_b: str) -> bool:
    repo_a = _github_owner_repo(url_a)
    repo_b = _github_owner_repo(url_b)
    if repo_a and repo_b:
        return repo_a[0].casefold() == repo_b[0].casefold() and repo_a[1].casefold() == repo_b[1].casefold()
    return url_a.strip().rstrip("/").casefold() == url_b.strip().rstrip("/").casefold()


async def _first_reachable(urls: list[str]) -> str | None:
    if not urls:
        return None
    import aiohttp

    timeout = aiohttp.ClientTimeout(total=_PIP_PROBE_TIMEOUT)

    async def probe(session: aiohttp.ClientSession, url: str) -> str | None:
        try:
            async with session.head(url, allow_redirects=True) as response:
                return url if response.status < 500 else None
        except (aiohttp.ClientError, asyncio.TimeoutError, OSError):
            return None

    try:
        async with aiohttp.ClientSession(timeout=timeout, trust_env=True) as session:
            results = await asyncio.gather(*(probe(session, url) for url in urls))
    except Exception:
        return None
    for url, result in zip(urls, results):
        if result:
            return url
    return None


def _launcher_directories() -> list[Path]:
    """ComfyUI 根目录与其祖先中的 ``.launcher`` 目录，最近的优先。"""
    roots: list[Path] = []
    try:
        import folder_paths

        roots.append(Path(folder_paths.__file__).resolve().parent)
    except (ImportError, AttributeError):
        pass
    roots.append(Path(__file__).resolve().parents[3])
    roots.append(Path(sys.executable).resolve().parent)
    directories: list[Path] = []
    seen: set[Path] = set()
    for root in roots:
        for ancestor in (root, *root.parents):
            candidate = ancestor / ".launcher"
            if candidate.is_dir() and candidate not in seen:
                seen.add(candidate)
                directories.append(candidate)
    return directories


def _read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


_cache: tuple[tuple[tuple[Path, int], ...], LauncherMirrors] | None = None


def active() -> LauncherMirrors:
    """当前生效的启动器镜像配置；文件 mtime 变化时自动重读。"""
    global _cache
    preference_paths: list[Path] = []
    for directory in _launcher_directories():
        if (directory / "preference.json").is_file():
            preference_paths.append(directory)
            break
    signature = tuple(
        (path, _mtime_ns(path / name))
        for path in preference_paths
        for name in ("preference.json", "data.json")
    )
    if _cache is not None and _cache[0] == signature:
        return _cache[1]
    mirrors = _load(preference_paths)
    _cache = (signature, mirrors)
    return mirrors


def _mtime_ns(path: Path) -> int:
    try:
        return path.stat().st_mtime_ns
    except OSError:
        return -1


def _load(directories: list[Path]) -> LauncherMirrors:
    if not directories:
        return LauncherMirrors()
    directory = directories[0]
    preference = _read_json(directory / "preference.json")
    network = preference.get("network_preference")
    if not isinstance(network, dict):
        network = {}
    data = _read_json(directory / "data.json")
    mirrors = data.get("mirrors")
    if not isinstance(mirrors, dict):
        mirrors = {}
    return LauncherMirrors(
        mirror_git=bool(network.get("mirror_git")),
        git_mirrors=[item for item in mirrors.get("git_mirrors") or [] if isinstance(item, dict)],
        mirror_pypi=bool(network.get("mirror_pypi")),
        pip_index=[item for item in mirrors.get("pip_index") or [] if isinstance(item, dict)],
        pip_trusted_host=[str(item) for item in mirrors.get("pip_trusted_host") or []],
    )


def reset_cache() -> None:
    """测试用：清空缓存与 pip 选择结果。"""
    global _cache
    _cache = None
