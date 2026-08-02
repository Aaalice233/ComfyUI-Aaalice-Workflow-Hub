from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass
from pathlib import Path
import re
import shutil
import subprocess
import sys
from typing import Any

from .errors import UserFacingError
from .security import ensure_within, parse_public_repository

_COMMIT_RE = r"[0-9a-f]{40}"
_GIT_TIMEOUT = 600


class GitCommandError(RuntimeError):
    def __init__(self, detail: str):
        self.detail = detail.strip() or "git command failed"
        super().__init__(self.detail)


@dataclass
class GitRepository:
    name: str
    path: Path
    source_url: str | None
    commit: str | None
    dirty: bool


@dataclass
class DependencyAction:
    registry_id: str | None
    source_url: str | None
    name: str
    requested: str | None
    installed: str | None
    action: str
    required: bool
    manual: bool
    installer: str = "git"
    warning_code: str | None = None
    warning_params: dict[str, str | int] | None = None


def _canonical_source(value: str | None) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        owner, repo = parse_public_repository(text)
    except ValueError:
        return None
    return f"https://github.com/{owner}/{repo}"


def _remote_source(value: str | None) -> str | None:
    text = str(value or "").strip()
    if text.startswith("git@github.com:"):
        text = f"https://github.com/{text.removeprefix('git@github.com:')}"
    elif text.startswith("ssh://git@github.com/"):
        text = f"https://github.com/{text.removeprefix('ssh://git@github.com/')}"
    return _canonical_source(text)


def _is_commit(value: str | None) -> bool:
    return bool(value and re.fullmatch(_COMMIT_RE, str(value).casefold()))


def _comfyui_root() -> Path:
    try:
        import folder_paths

        return Path(folder_paths.__file__).resolve().parent
    except (ImportError, AttributeError):
        return Path(__file__).resolve().parents[3]


def _custom_node_roots() -> list[Path]:
    try:
        import folder_paths

        roots = [Path(item).resolve() for item in folder_paths.get_folder_paths("custom_nodes")]
    except (ImportError, AttributeError, KeyError):
        roots = []
    if roots:
        return roots
    return [_comfyui_root() / "custom_nodes"]


def _git_executable() -> str | None:
    candidates: list[Path] = []
    prefix = Path(sys.prefix)
    candidates.extend((prefix / "Scripts" / "git.exe", prefix / "bin" / "git"))
    executable_dir = Path(sys.executable).resolve().parent
    candidates.extend((executable_dir / "git.exe", executable_dir / "Scripts" / "git.exe"))
    for root in (_comfyui_root(), _comfyui_root().parent):
        candidates.extend((root / "git" / "cmd" / "git.exe", root / "git" / "bin" / "git"))
    path_git = shutil.which("git")
    if path_git:
        candidates.append(Path(path_git))

    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    return None


async def _run_git(
    *args: str,
    cwd: Path | None = None,
    timeout: int = _GIT_TIMEOUT,
    on_log: Callable[[str], Awaitable[None]] | None = None,
) -> str:
    executable = _git_executable()
    if executable is None:
        raise UserFacingError("dependencies.git_unavailable")
    process = await asyncio.create_subprocess_exec(
        executable,
        *args,
        cwd=str(cwd) if cwd else None,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    async def read_stream(stream: asyncio.StreamReader) -> bytes:
        chunks: list[bytes] = []
        while True:
            chunk = await stream.read(4096)
            if not chunk:
                break
            chunks.append(chunk)
            if on_log:
                for line in chunk.decode(errors="replace").replace("\r", "\n").splitlines():
                    line = line.strip()
                    if line:
                        await on_log(line)
        return b"".join(chunks)

    try:
        stdout, stderr = await asyncio.wait_for(
            asyncio.gather(read_stream(process.stdout), read_stream(process.stderr)),
            timeout=timeout,
        )
    except asyncio.TimeoutError as exc:
        process.kill()
        await process.communicate()
        raise GitCommandError("git command timed out") from exc
    if process.returncode:
        detail = stderr.decode(errors="replace").strip() or stdout.decode(errors="replace").strip()
        raise GitCommandError(detail)
    return stdout.decode(errors="replace").strip()


async def _inspect_repository(path: Path) -> GitRepository | None:
    if not (path / ".git").exists():
        return None
    try:
        commit = (await _run_git("rev-parse", "HEAD", cwd=path, timeout=15)).casefold()
        remote = await _run_git("remote", "get-url", "origin", cwd=path, timeout=15)
        dirty = bool(await _run_git("status", "--porcelain", cwd=path, timeout=15))
    except (GitCommandError, UserFacingError):
        return None
    return GitRepository(path.name, path, _remote_source(remote), commit if _is_commit(commit) else None, dirty)


async def _scan_repositories() -> list[GitRepository]:
    if _git_executable() is None:
        raise UserFacingError("dependencies.git_unavailable")
    repositories: list[GitRepository] = []
    seen: set[Path] = set()
    for root in _custom_node_roots():
        if not root.is_dir():
            continue
        for path in sorted(root.iterdir(), key=lambda item: item.name.casefold()):
            if not path.is_dir() or path in seen:
                continue
            seen.add(path)
            repository = await _inspect_repository(path)
            if repository is not None:
                repositories.append(repository)
    return repositories


def _requested_commit(item: dict[str, Any]) -> str | None:
    commit = str(item.get("commit") or "").strip().casefold()
    if _is_commit(commit):
        return commit
    legacy_version = str(item.get("version") or "").strip().casefold()
    return legacy_version if _is_commit(legacy_version) else None


def _failure(item: dict[str, Any], code: str, params: dict[str, str | int] | None = None) -> dict[str, Any]:
    return {
        "name": str(item.get("name") or ""),
        "source_url": _canonical_source(item.get("source_url")),
        "requested": _requested_commit(item),
        "action": str(item.get("action") or ""),
        "state": "failed",
        "error_code": code,
        "error_params": params or {},
    }


class GitAdapter:
    async def installed_dependencies(self) -> list[dict[str, Any]]:
        repositories = await _scan_repositories()
        result = []
        for repository in repositories:
            if not repository.source_url or not repository.commit:
                continue
            result.append(
                {
                    "registry_id": None,
                    "source_url": repository.source_url,
                    "name": repository.name,
                    "version": None,
                    "commit": repository.commit,
                    "required": True,
                    "manual": True,
                    "dirty": repository.dirty,
                }
            )
        return result

    async def plan(self, dependencies: list[dict[str, Any]]) -> list[dict[str, Any]]:
        dependencies = [
            item for item in dependencies
            if item.get("source_url") or not item.get("registry_id")
        ]
        if not dependencies:
            return []
        installed = (
            {item.source_url: item for item in await _scan_repositories() if item.source_url}
            if any(item.get("source_url") for item in dependencies)
            else {}
        )
        requested_by_source: dict[str, set[str]] = {}
        for dependency in dependencies:
            source = _canonical_source(dependency.get("source_url"))
            requested = _requested_commit(dependency)
            if source and requested:
                requested_by_source.setdefault(source, set()).add(requested)

        result: list[DependencyAction] = []
        for dependency in dependencies:
            source = _canonical_source(dependency.get("source_url"))
            requested = _requested_commit(dependency)
            current = installed.get(source or "")
            installed_commit = current.commit if current else None
            warning_code = None
            warning_params: dict[str, str | int] = {}

            if source and len(requested_by_source.get(source, set())) > 1:
                action = "conflict"
                warning_code = "dependencies.conflicting_commits"
            elif not source:
                action = "manual"
                warning_code = "dependencies.github_source_missing"
            elif not requested:
                action = "manual"
                warning_code = "dependencies.commit_missing"
            elif not current:
                action = "install"
            elif current.dirty:
                action = "manual"
                warning_code = "dependencies.local_changes"
            elif installed_commit == requested:
                action = "keep"
            else:
                action = "upgrade"

            result.append(
                DependencyAction(
                    registry_id=str(dependency.get("registry_id") or "").strip() or None,
                    source_url=source,
                    name=str(dependency.get("name") or source or "GitHub repository"),
                    requested=requested,
                    installed=installed_commit,
                    action=action,
                    required=dependency.get("required", True),
                    manual=dependency.get("manual", True),
                    warning_code=warning_code,
                    warning_params=warning_params,
                )
            )
        return [asdict(item) for item in result]

    async def execute(
        self,
        actions: list[dict[str, Any]],
        on_log: Callable[[str], Awaitable[None]] | None = None,
        on_progress: Callable[[int, int], Awaitable[None]] | None = None,
        on_result: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
    ) -> list[dict[str, Any]]:
        executable = [item for item in actions if item.get("action") in {"install", "upgrade", "downgrade"}]
        results: list[dict[str, Any]] = []
        total = len(executable)
        for index, item in enumerate(executable, start=1):
            if on_log:
                await on_log(f"{item.get('name') or item.get('source_url')}: starting Git operation")
            result = await self._execute_one(item, on_log=on_log)
            results.append(result)
            if on_result:
                await on_result(result)
            if on_progress:
                await on_progress(index, total)
        return results

    async def _execute_one(
        self,
        item: dict[str, Any],
        on_log: Callable[[str], Awaitable[None]] | None = None,
    ) -> dict[str, Any]:
        source = _canonical_source(item.get("source_url"))
        requested = _requested_commit(item)
        if not source:
            return _failure(item, "dependencies.github_source_invalid")
        if not requested:
            return _failure(item, "dependencies.commit_missing")

        repositories = await _scan_repositories()
        current = next((repository for repository in repositories if repository.source_url == source), None)
        try:
            if current is not None:
                if current.dirty:
                    return _failure(item, "dependencies.local_changes")
                if on_log:
                    await on_log(f"{current.name}: fetching commit {requested}")
                await _run_git("fetch", "--no-tags", "origin", cwd=current.path, on_log=on_log)
                await _run_git("checkout", "--detach", requested, cwd=current.path, on_log=on_log)
            else:
                _owner, repo = parse_public_repository(source)
                root = _custom_node_roots()[0]
                root.mkdir(parents=True, exist_ok=True)
                target = ensure_within(root, root / repo)
                if target.exists():
                    return _failure(item, "dependencies.target_exists", {"path": target.name})
                if on_log:
                    await on_log(f"{repo}: cloning {source}")
                await _run_git("clone", "--progress", source, str(target), on_log=on_log)
                try:
                    await _run_git("checkout", "--detach", requested, cwd=target, on_log=on_log)
                except (GitCommandError, UserFacingError):
                    shutil.rmtree(target, ignore_errors=True)
                    raise
        except UserFacingError as exc:
            return _failure(item, exc.code, exc.params)
        except GitCommandError as exc:
            return _failure(item, "dependencies.git_command_failed", {"name": str(item.get("name") or source), "detail": exc.detail[-1000:]})
        return {
            "name": str(item.get("name") or source),
            "source_url": source,
            "requested": requested,
            "action": str(item.get("action") or ""),
            "state": "success",
            "error_code": None,
            "error_params": {},
        }


def local_git_status() -> dict[str, Any]:
    return {"available": _git_executable() is not None, "source": "github"}
