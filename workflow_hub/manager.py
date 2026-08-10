from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
from typing import Any

from .dependency_policy import is_ignored_dependency
from .errors import UserFacingError
from . import mirrors
from .security import ensure_within, parse_public_repository

_COMMIT_RE = r"[0-9a-f]{40}"
_GIT_TIMEOUT = 600


class GitCommandError(RuntimeError):
    def __init__(self, detail: str):
        self.detail = detail.strip() or "git command failed"
        super().__init__(self.detail)


class PythonDependencyError(RuntimeError):
    def __init__(self, detail: str):
        self.detail = detail.strip() or "python dependency installation failed"
        super().__init__(self.detail)


@dataclass
class GitRepository:
    name: str
    path: Path
    source_url: str | None
    commit: str | None
    dirty: bool
    detached: bool = False


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


def _source_key(value: str | None) -> str | None:
    source = _canonical_source(value)
    if not source:
        return None
    owner, repo = parse_public_repository(source)
    return f"https://github.com/{owner.casefold()}/{repo.casefold()}"


def _remote_source(value: str | None) -> str | None:
    # 启动器镜像（jihulab/gitee 映射、ghproxy 前缀等）克隆的工作副本 remote 不是
    # github.com，统一经 mirrors 归一化，保证插件识别与去重不受下载来源影响
    return mirrors.active().canonical_remote_url(str(value or ""))


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
    prefix = Path(sys.prefix)
    executable_dir = Path(sys.executable).resolve().parent
    comfyui_root = _comfyui_root()
    candidates = [
        prefix / "Scripts" / "git.exe",
        prefix / "bin" / "git",
        executable_dir / "git.exe",
        executable_dir / "Scripts" / "git.exe",
    ]
    xiaoziya_roots = [
        comfyui_root / ".xiaoziya",
        comfyui_root.parent / ".xiaoziya",
    ]
    if executable_dir.parent.name.casefold() == ".xiaoziya":
        xiaoziya_roots.append(executable_dir.parent)
    for root in xiaoziya_roots:
        portable_git = root / "PortableGit"
        candidates.extend(
            (
                portable_git / "cmd" / "git.exe",
                portable_git / "bin" / "git.exe",
                portable_git / "mingw64" / "bin" / "git.exe",
            )
        )
    for root in (comfyui_root, comfyui_root.parent):
        candidates.extend((root / "git" / "cmd" / "git.exe", root / "git" / "bin" / "git"))
    path_git = shutil.which("git")
    if path_git:
        candidates.append(Path(path_git))
    for candidate in dict.fromkeys(candidates):
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
    try:
        process = await asyncio.create_subprocess_exec(
            executable,
            *args,
            cwd=str(cwd) if cwd else None,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except OSError as exc:
        raise GitCommandError(str(exc)) from exc
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
    # 管道 EOF 不代表子进程退出状态已就绪，必须先 wait 再读 returncode
    await process.wait()
    if process.returncode:
        detail = stderr.decode(errors="replace").strip() or stdout.decode(errors="replace").strip()
        raise GitCommandError(detail)
    return stdout.decode(errors="replace").strip()


async def _install_python_requirements(
    repository: Path,
    on_log: Callable[[str], Awaitable[None]] | None = None,
) -> bool:
    requirements = repository / "requirements.txt"
    if not requirements.is_file():
        if on_log:
            await on_log(f"{repository.name}: no requirements.txt")
        return False
    if on_log:
        await on_log(f"{repository.name}: installing Python requirements.txt")
    mirror_args = await mirrors.active().select_pip_arguments()
    try:
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            "--no-input",
            *mirror_args,
            "-r",
            str(requirements),
            cwd=str(repository),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except OSError as exc:
        raise PythonDependencyError(str(exc)) from exc

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
            timeout=1800,
        )
    except asyncio.TimeoutError as exc:
        process.kill()
        await process.communicate()
        raise PythonDependencyError("pip install timed out") from exc
    # 管道 EOF 不代表子进程退出状态已就绪，必须先 wait 再读 returncode
    await process.wait()
    if process.returncode:
        detail = stderr.decode(errors="replace").strip() or stdout.decode(errors="replace").strip()
        raise PythonDependencyError(detail)
    if on_log:
        if mirror_args:
            await on_log(f"{repository.name}: Python requirements installed (index {mirror_args[1]})")
        else:
            await on_log(f"{repository.name}: Python requirements installed")
    return True


async def _default_branch(path: Path) -> str:
    try:
        ref = await _run_git("symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD", cwd=path, timeout=30)
        branch = ref.removeprefix("origin/").strip()
        if branch:
            return branch
    except GitCommandError:
        pass
    for candidate in ("main", "master"):
        try:
            await _run_git("show-ref", "--verify", f"refs/remotes/origin/{candidate}", cwd=path, timeout=30)
            return candidate
        except GitCommandError:
            continue
    raise GitCommandError("unable to determine the repository default branch")


async def _refresh_remote_refs(
    path: Path,
    source: str,
    on_log: Callable[[str], Awaitable[None]] | None,
) -> str:
    if on_log:
        await on_log("refreshing remote branches before checking local commits")
    try:
        await _run_git("fetch", "--no-tags", "origin", cwd=path, on_log=on_log)
    except GitCommandError as origin_error:
        errors = [f"origin: {origin_error.detail}"]
        for candidate in dict.fromkeys(mirrors.active().git_clone_candidates(source)):
            try:
                await _run_git(
                    "fetch",
                    "--no-tags",
                    candidate,
                    "+refs/heads/*:refs/remotes/origin/*",
                    cwd=path,
                    on_log=on_log,
                )
                break
            except GitCommandError as exc:
                errors.append(f"{candidate}: {exc.detail}")
        else:
            raise GitCommandError("; ".join(errors))

    unpushed = await _run_git("rev-list", "HEAD", "--not", "--remotes", cwd=path, timeout=30)
    if unpushed.strip():
        try:
            # 镜像可能落后于公开源；最后用 canonical GitHub refs 消除“远端引用过期”的误判。
            await _run_git(
                "fetch",
                "--no-tags",
                source,
                "+refs/heads/*:refs/remotes/origin/*",
                cwd=path,
                on_log=on_log,
            )
            unpushed = await _run_git("rev-list", "HEAD", "--not", "--remotes", cwd=path, timeout=30)
        except GitCommandError as exc:
            if on_log:
                await on_log(f"canonical remote refresh unavailable; preserving local-only commits: {exc.detail}")
    return unpushed


async def _backup_unpushed_head(path: Path, on_log: Callable[[str], Awaitable[None]] | None) -> str:
    short_commit = (await _run_git("rev-parse", "--short=12", "HEAD", cwd=path, timeout=30)).strip()
    backup_ref = f"workflow-hub-backup/{short_commit}-{time.time_ns()}"
    await _run_git("branch", backup_ref, "HEAD", cwd=path, timeout=30)
    if on_log:
        await on_log(f"preserved local-only commits on {backup_ref}")
    return backup_ref


async def _stash_worktree_changes(
    path: Path,
    on_log: Callable[[str], Awaitable[None]] | None,
    reason: str,
) -> str | None:
    if not await _run_git("status", "--porcelain", cwd=path, timeout=30):
        return None
    try:
        previous_stash = await _run_git("rev-parse", "--verify", "refs/stash", cwd=path, timeout=30)
    except GitCommandError:
        previous_stash = ""
    short_commit = (await _run_git("rev-parse", "--short=12", "HEAD", cwd=path, timeout=30)).strip()
    marker = f"workflow-hub-{reason}-{short_commit}-{time.time_ns()}"
    await _run_git("stash", "push", "--include-untracked", "--message", marker, cwd=path, timeout=120, on_log=on_log)
    stash_commit = await _run_git("rev-parse", "--verify", "refs/stash", cwd=path, timeout=30)
    if not stash_commit or stash_commit == previous_stash:
        raise GitCommandError("unable to preserve local working tree changes")
    backup_ref = f"refs/workflow-hub/backups/{marker}"
    try:
        await _run_git("update-ref", backup_ref, stash_commit, cwd=path, timeout=30)
        if await _run_git("status", "--porcelain", cwd=path, timeout=30):
            raise GitCommandError("unable to preserve all working tree changes")
    except GitCommandError as exc:
        try:
            await _run_git("stash", "apply", "--index", stash_commit, cwd=path, timeout=120, on_log=on_log)
        except GitCommandError as restore_exc:
            raise GitCommandError(f"{exc.detail}; restore failed: {restore_exc.detail}") from restore_exc
        raise
    if on_log:
        await on_log(f"preserved local working tree changes on {backup_ref}")
    return backup_ref


async def _restore_worktree_backup(
    path: Path,
    backup_ref: str | None,
    on_log: Callable[[str], Awaitable[None]] | None,
) -> None:
    if not backup_ref:
        return
    await _run_git("stash", "apply", "--index", backup_ref, cwd=path, timeout=120, on_log=on_log)
    if on_log:
        await on_log(f"restored local working tree changes from {backup_ref}")


async def _checkout_pinned(path: Path, requested: str, on_log: Callable[[str], Awaitable[None]] | None) -> None:
    # 只复用有对应远端的当前分支；本地临时分支和游离态都回到默认分支，保持启动器可更新。
    branch = (await _run_git("branch", "--show-current", cwd=path, timeout=30)).strip()
    if branch:
        try:
            await _run_git("rev-parse", "--verify", f"refs/remotes/origin/{branch}", cwd=path, timeout=30)
        except GitCommandError:
            branch = ""
    if not branch:
        branch = await _default_branch(path)
    await _run_git("checkout", "-B", branch, requested, cwd=path, on_log=on_log)
    await _run_git("branch", "--set-upstream-to", f"origin/{branch}", cwd=path, timeout=30)


async def _rollback_git_state(
    result: dict[str, Any],
    path: Path,
    on_log: Callable[[str], Awaitable[None]] | None = None,
) -> str | None:
    errors: list[str] = []
    if result.get("_cloned"):
        try:
            shutil.rmtree(path, ignore_errors=False)
            if on_log:
                await on_log(f"{path.name}: removed incomplete clone")
        except OSError as exc:
            errors.append(str(exc))
    elif result.get("_previous_commit"):
        try:
            previous_ref = str(result.get("_previous_ref") or "")
            if previous_ref:
                await _run_git("checkout", "-B", previous_ref, str(result["_previous_commit"]), cwd=path, on_log=on_log)
            else:
                await _run_git("checkout", "--detach", str(result["_previous_commit"]), cwd=path, on_log=on_log)
            if on_log:
                await on_log(f"{path.name}: restored previous commit")
        except GitCommandError as exc:
            errors.append(str(exc))
        try:
            await _restore_worktree_backup(path, result.get("_worktree_backup"), on_log)
        except GitCommandError as exc:
            errors.append(str(exc))
    return "; ".join(errors) or None


async def _inspect_repository(path: Path) -> GitRepository | None:
    if not (path / ".git").exists():
        return None
    try:
        commit = (await _run_git("rev-parse", "HEAD", cwd=path, timeout=15)).casefold()
        remote = await _run_git("remote", "get-url", "origin", cwd=path, timeout=15)
        dirty = bool(await _run_git("status", "--porcelain", cwd=path, timeout=15))
        detached = not (await _run_git("branch", "--show-current", cwd=path, timeout=15)).strip()
    except (GitCommandError, UserFacingError):
        return None
    return GitRepository(path.name, path, _remote_source(remote), commit if _is_commit(commit) else None, dirty, detached)


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


def _non_git_directory_names(repositories: list[GitRepository]) -> set[str]:
    git_paths = {repository.path.resolve() for repository in repositories}
    names: set[str] = set()
    for root in _custom_node_roots():
        if not root.is_dir():
            continue
        for path in root.iterdir():
            if path.is_dir() and path.resolve() not in git_paths:
                names.add(path.name.casefold())
    return names


def _requested_commit(item: dict[str, Any]) -> str | None:
    # 执行阶段收到的是 plan() 输出的字典，提交记录在 requested 字段；
    # 原始清单依赖使用 commit，历史清单可能把 SHA 放在 version。
    commit = str(item.get("commit") or item.get("requested") or "").strip().casefold()
    if _is_commit(commit):
        return commit
    legacy_version = str(item.get("version") or "").strip().casefold()
    return legacy_version if _is_commit(legacy_version) else None


def _public_git_result(result: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in result.items() if not key.startswith("_")}


def _failure(item: dict[str, Any], code: str, params: dict[str, str | int] | None = None) -> dict[str, Any]:
    return {
        "task_id": str(item.get("task_id") or ""),
        "name": str(item.get("name") or ""),
        "source_url": _canonical_source(item.get("source_url")),
        "requested": _requested_commit(item),
        "action": str(item.get("action") or ""),
        "installer": "git",
        "state": "failed",
        "error_code": code,
        "error_params": params or {},
    }


class GitAdapter:
    async def installed_dependencies(self) -> list[dict[str, Any]]:
        repositories = await _scan_repositories()
        result = []
        for repository in repositories:
            if (
                not repository.source_url
                or not repository.commit
                or is_ignored_dependency({"name": repository.name, "source_url": repository.source_url})
            ):
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
                    "installer": "git",
                    "dirty": repository.dirty,
                }
            )
        return result

    async def plan(self, dependencies: list[dict[str, Any]], align_versions: bool = True) -> list[dict[str, Any]]:
        dependencies = [
            item for item in dependencies
            if (item.get("source_url") or not item.get("registry_id"))
            and not is_ignored_dependency(item)
        ]
        if not dependencies:
            return []
        installed: dict[str, list[GitRepository]] = {}
        repositories_by_path: dict[Path, GitRepository] = {}
        non_git_directories: set[str] = set()
        install_root: Path | None = None
        if any(item.get("source_url") for item in dependencies):
            repositories = await _scan_repositories()
            for repository in repositories:
                key = _source_key(repository.source_url)
                if key:
                    installed.setdefault(key, []).append(repository)
                repositories_by_path[repository.path.resolve()] = repository
            non_git_directories = _non_git_directory_names(repositories)
            install_root = _custom_node_roots()[0]
        requested_by_source: dict[str, set[str]] = {}
        requested_by_target: dict[str, set[str]] = {}
        for dependency in dependencies:
            source = _canonical_source(dependency.get("source_url"))
            requested = _requested_commit(dependency)
            if source and requested:
                source_key = _source_key(source) or source
                requested_by_source.setdefault(source_key, set()).add(requested)
                requested_by_target.setdefault(parse_public_repository(source)[1].casefold(), set()).add(source_key)

        result: list[DependencyAction] = []
        for dependency in dependencies:
            source = _canonical_source(dependency.get("source_url"))
            source_key = _source_key(source)
            requested = _requested_commit(dependency)
            matches = installed.get(source_key or "", [])
            duplicate_source = len(matches) > 1
            current = matches[0] if len(matches) == 1 else None
            installed_commit = current.commit if current else None
            warning_code = None
            warning_params: dict[str, str | int] = {}
            dependency_name = str(dependency.get("name") or source or "GitHub repository")
            target: Path | None = None
            target_repository: GitRepository | None = None
            if source and install_root is not None:
                _owner, repo = parse_public_repository(source)
                target = ensure_within(install_root, install_root / repo)
                target_repository = repositories_by_path.get(target.resolve())

            if source and duplicate_source:
                action = "manual"
                warning_code = "dependencies.duplicate_git_source"
            elif source and len(requested_by_source.get(_source_key(source) or source, set())) > 1:
                action = "conflict"
                warning_code = "dependencies.conflicting_commits"
            elif target is not None and len(requested_by_target.get(target.name.casefold(), set())) > 1:
                action = "manual"
                warning_code = "dependencies.target_exists"
                warning_params = {"path": target.name}
            elif not source:
                action = "manual"
                warning_code = "dependencies.github_source_missing"
            elif not requested:
                action = "manual"
                warning_code = "dependencies.commit_missing"
            elif parse_public_repository(source)[1].casefold() in non_git_directories:
                action = "manual"
                warning_code = "dependencies.non_git_install"
            elif not current and target is not None and target.exists():
                action = "manual"
                if target_repository is not None:
                    warning_code = "dependencies.target_exists"
                    warning_params = {"path": target.name}
                else:
                    warning_code = "dependencies.non_git_install"
            elif not current:
                action = "install"
            elif current.dirty:
                # 同步会先把 tracked/untracked 改动保存到独立 Git ref，再恢复干净的跟踪分支。
                action = "upgrade"
            elif installed_commit == requested:
                # 游离态但 commit 已对齐：提供补全把工作副本挂回本地分支
                action = "upgrade" if current.detached else "keep"
            elif not align_versions:
                action = "manual"
                warning_code = "dependencies.version_alignment_disabled"
                warning_params = {"installed": installed_commit, "requested": requested}
            else:
                action = "upgrade"

            result.append(
                DependencyAction(
                    registry_id=str(dependency.get("registry_id") or "").strip() or None,
                    source_url=source,
                    name=dependency_name,
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
        executable = [
            item for item in actions
            if item.get("action") in {"install", "upgrade", "downgrade"}
            and not is_ignored_dependency(item)
        ]
        if not executable:
            return []
        repositories = await _scan_repositories()
        unique: dict[str, dict[str, Any]] = {}
        for item in executable:
            source = _source_key(item.get("source_url"))
            unique.setdefault(source or str(item.get("name") or "").casefold(), item)
        executable = list(unique.values())
        total = len(executable) * 2
        results: list[dict[str, Any]] = []
        for index, item in enumerate(executable):
            result, path = await self._execute_git_one(item, repositories, on_log=on_log)
            installing = _public_git_result(result)
            if installing.get("state") == "success":
                installing["state"] = "installing"
            if on_result:
                await on_result(installing)
            if on_progress:
                await on_progress(index * 2 + 1, total)

            final = dict(result)
            if final.get("state") == "success" and path is not None:
                name = str(final.get("name") or path.name)

                async def requirements_log(line: str) -> None:
                    if on_log:
                        await on_log(f"{name}: {line}")

                def add_backup_ref(backup_ref: str | None) -> None:
                    if not backup_ref:
                        return
                    backup_refs = list(final.get("backup_refs") or [])
                    if backup_ref not in backup_refs:
                        backup_refs.append(backup_ref)
                    final["backup_refs"] = backup_refs
                    final["backup_ref"] = backup_refs[0]

                try:
                    python_state = {**_public_git_result(final), "state": "python_installing"}
                    if on_result:
                        await on_result(python_state)
                    installed = await _install_python_requirements(path, on_log=requirements_log)
                    final["python_requirements"] = "installed" if installed else "not_required"
                    add_backup_ref(await _stash_worktree_changes(path, requirements_log, "requirements"))
                except (PythonDependencyError, GitCommandError) as exc:
                    preserve_error = None
                    if isinstance(exc, PythonDependencyError) and not final.get("_cloned"):
                        try:
                            add_backup_ref(await _stash_worktree_changes(path, requirements_log, "requirements-failed"))
                        except GitCommandError as backup_exc:
                            preserve_error = backup_exc.detail
                    rollback_detail = await _rollback_git_state(final, path, on_log)
                    detail = exc.detail[-1000:]
                    if preserve_error:
                        detail = f"{detail}; preserving generated changes failed: {preserve_error}"
                    if rollback_detail:
                        detail = f"{detail}; rollback failed: {rollback_detail}"
                    failed = _failure(
                        item,
                        "dependencies.python_requirements_failed",
                        {"name": name, "detail": detail},
                    )
                    if final.get("backup_refs"):
                        failed["backup_refs"] = final["backup_refs"]
                        failed["backup_ref"] = final["backup_refs"][0]
                    final = failed
            public_result = _public_git_result(final)
            results.append(public_result)
            if on_result:
                await on_result(public_result)
            if on_progress:
                await on_progress((index + 1) * 2, total)
        return results

    async def _execute_git_one(
        self,
        item: dict[str, Any],
        repositories: list[GitRepository],
        on_log: Callable[[str], Awaitable[None]] | None = None,
    ) -> tuple[dict[str, Any], Path | None]:
        source = _canonical_source(item.get("source_url"))
        requested = _requested_commit(item)
        if not source:
            return _failure(item, "dependencies.github_source_invalid"), None
        if not requested:
            return _failure(item, "dependencies.commit_missing"), None

        name = str(item.get("name") or source)

        async def git_log(line: str) -> None:
            if on_log:
                await on_log(f"{name}: {line}")

        matches = [repository for repository in repositories if _source_key(repository.source_url) == _source_key(source)]
        if len(matches) > 1:
            return _failure(item, "dependencies.duplicate_git_source"), None
        current = matches[0] if matches else None
        _owner, repo = parse_public_repository(source)
        root = _custom_node_roots()[0]
        target = ensure_within(root, root / repo)
        if current is None and target.exists():
            target_repository = await _inspect_repository(target) if target.is_dir() else None
            if target_repository is None:
                return _failure(item, "dependencies.non_git_install"), None
            if _source_key(target_repository.source_url) != _source_key(source):
                return _failure(item, "dependencies.target_exists", {"path": target.name}), None
            current = target_repository

        clone_candidates = mirrors.active().git_clone_candidates(source)

        async def ensure_commit(path: Path) -> None:
            try:
                await _run_git("cat-file", "-e", f"{requested}^{{commit}}", cwd=path, timeout=30)
                return
            except GitCommandError:
                pass
            # origin 可能是滞后于 GitHub 的镜像；逐个候选源拉取直到拿到钉住的 commit
            remotes = ["origin", *(url for url in clone_candidates if url != "origin")]
            errors: list[str] = []
            for remote in dict.fromkeys(remotes):
                try:
                    await _run_git("fetch", "--no-tags", remote, requested, cwd=path, on_log=git_log)
                    return
                except GitCommandError as exc:
                    errors.append(f"{remote}: {exc.detail}")
            raise GitCommandError("; ".join(errors))

        try:
            if current is not None:
                previous_commit = (await _run_git("rev-parse", "HEAD", cwd=current.path, timeout=30)).strip().casefold()
                previous_ref = (await _run_git("branch", "--show-current", cwd=current.path, timeout=30)).strip()
                worktree_backup = await _stash_worktree_changes(current.path, git_log, "worktree")
                rollback_state = {
                    "_cloned": False,
                    "_previous_commit": previous_commit,
                    "_previous_ref": previous_ref,
                    "_worktree_backup": worktree_backup,
                }
                backup_refs = [worktree_backup] if worktree_backup else []
                try:
                    unpushed = await _refresh_remote_refs(current.path, source, git_log)
                    await git_log(f"fetching commit {requested}")
                    await ensure_commit(current.path)
                    if unpushed.strip():
                        backup_refs.append(await _backup_unpushed_head(current.path, git_log))
                    await _checkout_pinned(current.path, requested, git_log)
                    actual = await _run_git("rev-parse", "HEAD", cwd=current.path, timeout=30)
                    if actual.casefold() != requested.casefold():
                        raise GitCommandError(f"checked out {actual}, expected {requested}")
                except GitCommandError as exc:
                    rollback_detail = await _rollback_git_state(rollback_state, current.path, git_log)
                    detail = exc.detail
                    if rollback_detail:
                        detail = f"{detail}; rollback failed: {rollback_detail}"
                    raise GitCommandError(detail) from exc
                return {
                    "task_id": str(item.get("task_id") or ""),
                    "name": name,
                    "source_url": source,
                    "requested": requested,
                    "action": str(item.get("action") or ""),
                    "installer": "git",
                    "state": "success",
                    "error_code": None,
                    "error_params": {},
                    "backup_ref": backup_refs[0] if backup_refs else None,
                    "backup_refs": backup_refs,
                    "_worktree_backup": worktree_backup,
                    "_previous_commit": previous_commit,
                    "_previous_ref": previous_ref,
                    "_cloned": False,
                }, current.path

            root.mkdir(parents=True, exist_ok=True)
            await git_log(f"cloning {source}")
            created = False
            try:
                clone_error: GitCommandError | None = None
                for candidate in clone_candidates:
                    if candidate != source:
                        await git_log(f"trying launcher mirror {candidate}")
                    try:
                        await _run_git("clone", "--progress", candidate, str(target), on_log=git_log)
                        clone_error = None
                        break
                    except GitCommandError as exc:
                        clone_error = exc
                        shutil.rmtree(target, ignore_errors=True)
                if clone_error is not None:
                    raise clone_error
                created = True
                await ensure_commit(target)
                await _checkout_pinned(target, requested, git_log)
                actual = await _run_git("rev-parse", "HEAD", cwd=target, timeout=30)
                if actual.casefold() != requested.casefold():
                    raise GitCommandError(f"checked out {actual}, expected {requested}")
            except (GitCommandError, UserFacingError):
                if created or target.exists():
                    shutil.rmtree(target, ignore_errors=True)
                raise
            return {
                "task_id": str(item.get("task_id") or ""),
                "name": name,
                "source_url": source,
                "requested": requested,
                "action": str(item.get("action") or ""),
                "installer": "git",
                "state": "success",
                "error_code": None,
                "error_params": {},
                "_previous_commit": None,
                "_cloned": True,
            }, target
        except UserFacingError as exc:
            return _failure(item, exc.code, exc.params), None
        except GitCommandError as exc:
            return _failure(item, "dependencies.git_command_failed", {"name": name, "detail": exc.detail[-1000:]}), None


def local_git_status() -> dict[str, Any]:
    active_mirrors = mirrors.active()
    return {
        "available": _git_executable() is not None,
        "source": "github",
        "launcher_mirrors": {
            "detected": active_mirrors.available,
            "git": active_mirrors.mirror_git,
            "pypi": active_mirrors.mirror_pypi,
        },
    }
