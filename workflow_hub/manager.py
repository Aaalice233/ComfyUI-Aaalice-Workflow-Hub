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

from .dependency_policy import is_ignored_dependency
from .errors import UserFacingError
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
    try:
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            "--no-input",
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


async def _checkout_pinned(path: Path, requested: str, on_log: Callable[[str], Awaitable[None]] | None) -> None:
    # 钉在锁定 commit 但保持本地分支与 upstream 跟踪，避免游离态阻断启动器/Manager 的更新
    branch = (await _run_git("branch", "--show-current", cwd=path, timeout=30)).strip()
    if not branch:
        branch = await _default_branch(path)
    await _run_git("checkout", "-B", branch, requested, cwd=path, on_log=on_log)
    try:
        await _run_git("rev-parse", "--verify", f"refs/remotes/origin/{branch}", cwd=path, timeout=30)
    except GitCommandError:
        return
    await _run_git("branch", "--set-upstream-to", f"origin/{branch}", cwd=path, timeout=30)


async def _rollback_git_state(
    result: dict[str, Any],
    path: Path,
    on_log: Callable[[str], Awaitable[None]] | None = None,
) -> str | None:
    try:
        if result.get("_cloned"):
            shutil.rmtree(path, ignore_errors=False)
            if on_log:
                await on_log(f"{path.name}: removed incomplete clone")
        elif result.get("_previous_commit"):
            previous_ref = str(result.get("_previous_ref") or "")
            if previous_ref:
                await _run_git("checkout", "-B", previous_ref, str(result["_previous_commit"]), cwd=path, on_log=on_log)
            else:
                await _run_git("checkout", "--detach", str(result["_previous_commit"]), cwd=path, on_log=on_log)
            if on_log:
                await on_log(f"{path.name}: restored previous commit")
    except (GitCommandError, OSError) as exc:
        return str(exc)
    return None


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
        if any(item.get("source_url") for item in dependencies):
            for repository in await _scan_repositories():
                key = _source_key(repository.source_url)
                if key:
                    installed.setdefault(key, []).append(repository)
        requested_by_source: dict[str, set[str]] = {}
        for dependency in dependencies:
            source = _canonical_source(dependency.get("source_url"))
            requested = _requested_commit(dependency)
            if source and requested:
                requested_by_source.setdefault(_source_key(source) or source, set()).add(requested)

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

            if source and duplicate_source:
                action = "manual"
                warning_code = "dependencies.duplicate_git_source"
            elif source and len(requested_by_source.get(_source_key(source) or source, set())) > 1:
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
        git_done = 0
        source_locks: dict[str, asyncio.Lock] = {}
        target_locks: dict[str, asyncio.Lock] = {}
        semaphore = asyncio.Semaphore(min(4, len(executable)))
        root = _custom_node_roots()[0]

        def target_key(item: dict[str, Any]) -> str:
            source = _canonical_source(item.get("source_url"))
            if source:
                _owner, repo = parse_public_repository(source)
                return str(ensure_within(root, root / repo)).casefold()
            return str(item.get("name") or "").casefold()

        async def run_git(index: int, item: dict[str, Any]) -> tuple[int, dict[str, Any], Path | None]:
            source = _source_key(item.get("source_url")) or str(item.get("name") or "").casefold()
            source_lock = source_locks.setdefault(source, asyncio.Lock())
            path_lock = target_locks.setdefault(target_key(item), asyncio.Lock())
            async with semaphore, source_lock, path_lock:
                result, path = await self._execute_git_one(item, repositories, on_log=on_log)
                return index, result, path

        git_results: list[tuple[dict[str, Any], Path | None] | None] = [None] * len(executable)
        results: list[dict[str, Any]] = [{} for _ in executable]
        git_tasks = [asyncio.create_task(run_git(index, item)) for index, item in enumerate(executable)]
        try:
            for completed_task in asyncio.as_completed(git_tasks):
                index, result, path = await completed_task
                git_results[index] = (result, path)
                installing = _public_git_result(result)
                if installing.get("state") == "success":
                    installing["state"] = "installing"
                results[index] = installing
                if on_result:
                    await on_result(installing)
                git_done += 1
                if on_progress:
                    await on_progress(git_done, total)
        except BaseException:
            for task in git_tasks:
                task.cancel()
            await asyncio.gather(*git_tasks, return_exceptions=True)
            raise

        python_done = 0
        for index, item_result in enumerate(git_results):
            if item_result is None:
                continue
            result, path = item_result
            final = dict(result)
            if final.get("state") == "success" and path is not None:
                name = str(final.get("name") or path.name)

                async def requirements_log(line: str) -> None:
                    if on_log:
                        await on_log(f"{name}: {line}")

                try:
                    python_state = {**_public_git_result(final), "state": "python_installing"}
                    if on_result:
                        await on_result(python_state)
                    installed = await _install_python_requirements(path, on_log=requirements_log)
                    final["python_requirements"] = "installed" if installed else "not_required"
                except PythonDependencyError as exc:
                    rollback_detail = await _rollback_git_state(final, path, on_log)
                    detail = exc.detail[-1000:]
                    if rollback_detail:
                        detail = f"{detail}; rollback failed: {rollback_detail}"
                    final = _failure(
                        executable[index],
                        "dependencies.python_requirements_failed",
                        {"name": name, "detail": detail},
                    )
            results[index] = _public_git_result(final)
            if on_result:
                await on_result(results[index])
            python_done += 1
            if on_progress:
                await on_progress(len(executable) + python_done, total)
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

        async def ensure_commit(path: Path) -> None:
            try:
                await _run_git("cat-file", "-e", f"{requested}^{{commit}}", cwd=path, timeout=30)
            except GitCommandError:
                await _run_git("fetch", "--no-tags", "origin", requested, cwd=path, on_log=git_log)

        try:
            if current is not None:
                if current.dirty:
                    return _failure(item, "dependencies.local_changes"), None
                dirty = await _run_git("status", "--porcelain", cwd=current.path, timeout=30)
                if dirty:
                    return _failure(item, "dependencies.local_changes"), None
                unpushed = await _run_git("rev-list", "HEAD", "--not", "--remotes", cwd=current.path, timeout=30)
                if unpushed.strip():
                    return _failure(item, "dependencies.unpushed_commits", {"name": name}), None
                previous_ref = (await _run_git("branch", "--show-current", cwd=current.path, timeout=30)).strip()
                await git_log(f"fetching commit {requested}")
                await ensure_commit(current.path)
                await _checkout_pinned(current.path, requested, git_log)
                actual = await _run_git("rev-parse", "HEAD", cwd=current.path, timeout=30)
                if actual.casefold() != requested.casefold():
                    raise GitCommandError(f"checked out {actual}, expected {requested}")
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
                    "_previous_commit": current.commit,
                    "_previous_ref": previous_ref,
                    "_cloned": False,
                }, current.path

            _owner, repo = parse_public_repository(source)
            root = _custom_node_roots()[0]
            root.mkdir(parents=True, exist_ok=True)
            target = ensure_within(root, root / repo)
            if target.exists():
                return _failure(item, "dependencies.target_exists", {"path": target.name}), None
            await git_log(f"cloning {source}")
            created = False
            try:
                await _run_git("clone", "--progress", source, str(target), on_log=git_log)
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
    return {"available": _git_executable() is not None, "source": "github"}
