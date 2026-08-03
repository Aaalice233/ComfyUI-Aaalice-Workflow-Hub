from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass
import asyncio
import re
from typing import Any

from .security import parse_public_repository

import aiohttp

from .errors import UserFacingError

_flavor_cache: dict[str, tuple[str, str]] = {}


def _parse_version(value: str) -> tuple[int, ...]:
    try:
        return tuple(int(part) for part in str(value).lstrip("Vv").split(".")[:3])
    except ValueError:
        return ()


def _github_url(value: str | None) -> str | None:
    text = str(value or "").strip().strip("/")
    if text.startswith("github:"):
        text = text.removeprefix("github:")
    if text.startswith("git@github.com:"):
        text = text.removeprefix("git@github.com:")
    elif text.startswith("ssh://git@github.com/"):
        text = text.removeprefix("ssh://git@github.com/")
    elif text.startswith("https://github.com/"):
        text = text.removeprefix("https://github.com/")
    elif text.startswith("github.com/"):
        text = text.removeprefix("github.com/")
    text = text.removesuffix(".git").strip("/")
    try:
        owner, repo = parse_public_repository(text)
    except ValueError:
        return None
    return f"https://github.com/{owner}/{repo}"


def _version_tuple(value: str | None) -> tuple[int, int, int] | None:
    match = re.fullmatch(r"\d+(?:\.\d+){0,2}", str(value or "").strip().lstrip("vV"))
    if not match:
        return None
    parts = [int(part) for part in match.group(0).split(".")]
    return tuple((parts + [0, 0, 0])[:3])  # type: ignore[return-value]


def _manager_compatible(flavor: str, version: str | None) -> bool:
    numbers = _version_tuple(version)
    if numbers is None:
        return False
    return numbers[0] == 3 if flavor == "legacy" else numbers >= (4, 2, 1)


def _source_from_aux(value: str | None) -> str | None:
    return _github_url(value)


@dataclass
class ManagerAction:
    registry_id: str | None
    source_url: str | None
    name: str
    requested: str | None
    installed: str | None
    action: str
    required: bool
    manual: bool
    installer: str = "manager"
    warning_code: str | None = None
    warning_params: dict[str, str | int] | None = None


class ManagerAdapter:
    def __init__(self, origin: str):
        self.origin = origin.rstrip("/")

    async def _detect(self) -> tuple[str, str] | None:
        cached = _flavor_cache.get(self.origin)
        if cached is not None:
            return cached
        try:
            async with aiohttp.ClientSession(trust_env=True) as session:
                for flavor, path in (("v2", "/v2/manager/version"), ("legacy", "/manager/version")):
                    try:
                        async with session.get(f"{self.origin}{path}", timeout=3) as response:
                            if response.status != 200:
                                continue
                            version = (await response.text()).strip().strip('"')
                            if _version_tuple(version) is None:
                                continue
                            detected = (flavor, version)
                            _flavor_cache[self.origin] = detected
                            return detected
                    except (aiohttp.ClientError, asyncio.TimeoutError, OSError):
                        continue
        except (aiohttp.ClientError, asyncio.TimeoutError, OSError):
            pass
        return None

    async def status(self) -> dict[str, Any]:
        detected = await self._detect()
        if detected is None:
            return {"available": False, "compatible": False}
        return {
            "available": True,
            "compatible": _manager_compatible(detected[0], detected[1]),
            "version": detected[1],
            "api": detected[0],
        }

    async def _require_compatible(self) -> tuple[str, str]:
        detected = await self._detect()
        if detected is None:
            raise UserFacingError("dependencies.manager_unavailable")
        if not _manager_compatible(*detected):
            raise UserFacingError("dependencies.manager_incompatible", {"version": detected[1]})
        return detected

    async def installed(self) -> dict[str, dict[str, Any]]:
        detected = await self._require_compatible()
        path = "/v2/customnode/installed" if detected[0] == "v2" else "/customnode/installed"
        try:
            async with aiohttp.ClientSession(trust_env=True) as session:
                async with session.get(f"{self.origin}{path}", timeout=5) as response:
                    if response.status != 200:
                        raise UserFacingError("dependencies.manager_request_failed", {"status": response.status})
                    data = await response.json()
        except UserFacingError:
            raise
        except (aiohttp.ClientError, asyncio.TimeoutError, OSError, ValueError) as exc:
            raise UserFacingError(
                "dependencies.manager_request_failed",
                {"status": 0, "detail": str(exc) or exc.__class__.__name__},
            ) from exc
        if isinstance(data, dict):
            result: dict[str, dict[str, Any]] = {}
            for module_name, item in data.items():
                if not isinstance(item, dict):
                    continue
                registry_id = str(item.get("cnr_id") or item.get("id") or "").strip() or None
                aux_id = str(item.get("aux_id") or "").strip() or None
                aux_source = _source_from_aux(aux_id)
                key = registry_id or (f"github:{aux_source.casefold()}" if aux_source else f"module:{module_name}")
                result[key] = {
                    **item,
                    "registry_id": registry_id,
                    "aux_id": aux_id,
                    "module_name": module_name,
                    "name": str(item.get("name") or item.get("title") or module_name),
                    "version": item.get("version") or item.get("ver"),
                }
            return result
        if not isinstance(data, list):
            raise UserFacingError("dependencies.manager_request_failed", {"status": 0, "detail": "invalid installed-plugin response"})
        return {
            str(item.get("id")): {
                **item,
                "registry_id": item.get("cnr_id") or item.get("id"),
                "aux_id": item.get("aux_id"),
                "module_name": item.get("module_name") or item.get("name") or item.get("id"),
                "name": str(item.get("name") or item.get("title") or item.get("id")),
                "version": item.get("version") or item.get("ver"),
            }
            for item in data
            if isinstance(item, dict) and item.get("id")
        }

    async def installed_dependencies(self) -> list[dict[str, Any]]:
        installed = await self.installed()
        result: list[dict[str, Any]] = []
        for item in installed.values():
            registry_id = str(item.get("registry_id") or "").strip() or None
            if not registry_id:
                continue
            source_url = _source_from_aux(item.get("aux_id"))
            version = str(item.get("version") or "").strip() or None
            git_worktree = bool(source_url and version and re.fullmatch(r"[0-9a-fA-F]{40}", version))
            result.append(
                {
                    "registry_id": None if git_worktree else registry_id,
                    "source_url": source_url if git_worktree else None,
                    "name": str(item.get("name") or item.get("module_name") or registry_id),
                    "version": None if git_worktree else version,
                    "commit": version if git_worktree else None,
                    "required": True,
                    "manual": git_worktree,
                    "installer": "git" if git_worktree else "manager",
                    "dirty": False,
                }
            )
        return result

    @staticmethod
    def _find_installed(installed: dict[str, dict[str, Any]], dependency: dict[str, Any]) -> dict[str, Any] | None:
        registry_id = str(dependency.get("registry_id") or "").strip()
        source = _source_from_aux(dependency.get("source_url"))
        names = {
            str(dependency.get("name") or "").strip().casefold(),
            str(dependency.get("module_name") or "").strip().casefold(),
        } - {""}
        for key in (registry_id, f"github:{source.casefold()}" if source else ""):
            if key and key in installed:
                return installed[key]
        if registry_id:
            match = next(
                (item for item in installed.values() if str(item.get("registry_id") or "").strip().casefold() == registry_id.casefold()),
                None,
            )
            if match is not None:
                return match
        if source:
            match = next(
                (item for item in installed.values() if (_source_from_aux(item.get("aux_id")) or "").casefold() == source.casefold()),
                None,
            )
            if match is not None:
                return match
        matches = [
            item for item in installed.values()
            if str(item.get("module_name") or item.get("name") or "").strip().casefold() in names
        ]
        return matches[0] if len(matches) == 1 else None

    async def plan(self, dependencies: list[dict[str, Any]], align_versions: bool = True) -> list[dict[str, Any]]:
        registry_dependencies = [item for item in dependencies if item.get("registry_id") and not item.get("source_url")]
        if not registry_dependencies:
            return []
        detected = await self._detect()
        compatible = detected is not None and _manager_compatible(*detected)
        installed_error: UserFacingError | None = None
        try:
            installed = await self.installed() if compatible else {}
        except UserFacingError as exc:
            installed = {}
            installed_error = exc
        requested_by_id: dict[str, set[str]] = {}
        for dependency in registry_dependencies:
            version = str(dependency.get("version") or "").strip()
            if version:
                requested_by_id.setdefault(str(dependency["registry_id"]), set()).add(version)
        result: list[ManagerAction] = []
        for dependency in registry_dependencies:
            registry_id = str(dependency["registry_id"])
            requested = str(dependency.get("version") or "").strip() or None
            current = self._find_installed(installed, dependency)
            installed_version = str(current.get("version") or "").strip() or None if current else None
            if len(requested_by_id.get(registry_id, set())) > 1:
                action, warning_code = "conflict", "dependencies.conflicting_registry_versions"
            elif installed_error is not None:
                action, warning_code = "manual", installed_error.code
            elif not compatible:
                action = "manual"
                warning_code = "dependencies.manager_incompatible" if detected else "dependencies.manager_unavailable"
            elif not current:
                action, warning_code = "install", None
            elif not requested:
                action, warning_code = "keep", None
            else:
                current_numbers = _version_tuple(installed_version)
                requested_numbers = _version_tuple(requested)
                if current_numbers is not None and requested_numbers is not None and current_numbers == requested_numbers:
                    action, warning_code = "keep", None
                elif current_numbers is None or requested_numbers is None:
                    action, warning_code = "unknown", "dependencies.manager_version_unknown"
                elif not align_versions:
                    action, warning_code = "manual", "dependencies.version_alignment_disabled"
                else:
                    action = "upgrade" if current_numbers < requested_numbers else "downgrade"
                    warning_code = None
            result.append(
                ManagerAction(
                    registry_id=registry_id,
                    source_url=None,
                    name=str(dependency.get("name") or registry_id),
                    requested=requested,
                    installed=installed_version,
                    action=action,
                    required=dependency.get("required", True),
                    manual=False,
                    warning_code=warning_code,
                    warning_params=(
                        installed_error.params
                        if installed_error is not None
                        else {"version": detected[1]} if warning_code == "dependencies.manager_incompatible" and detected else {}
                    ),
                )
            )
        return [asdict(item) for item in result]

    async def execute(
        self,
        actions: list[dict[str, Any]],
        client_id: str,
        on_queued: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
    ) -> list[dict[str, Any]]:
        executable = [item for item in actions if item.get("registry_id") and item.get("action") in {"install", "upgrade", "downgrade"}]
        if not executable:
            return []
        detected = await self._require_compatible()
        queued: list[dict[str, Any]] = []
        async with aiohttp.ClientSession(trust_env=True, timeout=aiohttp.ClientTimeout(total=30)) as session:
            for item in executable:
                target_version = item.get("requested") or "latest"
                if detected[0] == "legacy":
                    request = session.post(
                        f"{self.origin}/manager/queue/install",
                        json={
                            "id": item["registry_id"],
                            "version": target_version,
                            "selected_version": target_version,
                            "skip_post_install": False,
                            "ui_id": item["registry_id"],
                            "channel": "default",
                            "mode": "cache",
                        },
                    )
                else:
                    request = session.post(
                        f"{self.origin}/v2/manager/queue/task",
                        json={
                            "ui_id": item["registry_id"],
                            "client_id": client_id,
                            "kind": "install",
                            "params": {
                                "id": item["registry_id"],
                                "version": target_version,
                                "selected_version": target_version,
                                "mode": "cache",
                                "channel": "default",
                                "skip_post_install": False,
                            },
                        },
                    )
                async with request as response:
                    if response.status not in (200, 201):
                        raise UserFacingError("dependencies.manager_request_failed", {"status": response.status})
                queued.append(item)
                if on_queued:
                    await on_queued(item)
            if detected[0] == "legacy":
                request = session.get(f"{self.origin}/manager/queue/start")
            else:
                request = session.post(f"{self.origin}/v2/manager/queue/start", json={"client_id": client_id})
            async with request as response:
                if response.status not in (200, 201):
                    raise UserFacingError("dependencies.manager_request_failed", {"status": response.status})
        return queued

    async def verify_actions(self, actions: list[dict[str, Any]]) -> dict[str, dict[str, str]]:
        installed = await self.installed()
        result: dict[str, dict[str, str]] = {}
        for action in actions:
            registry_id = str(action.get("registry_id") or "")
            current = self._find_installed(installed, action)
            requested = str(action.get("requested") or "").strip()
            if current is None:
                result[registry_id] = {"state": "failed", "message": "plugin is not present after installation"}
                continue
            installed_version = str(current.get("version") or "").strip()
            requested_numbers = _version_tuple(requested)
            version_matches = (
                _version_tuple(installed_version) == requested_numbers
                if requested_numbers is not None
                else installed_version.casefold() == requested.casefold()
            )
            if requested and not version_matches:
                result[registry_id] = {
                    "state": "failed",
                    "message": f"installed version {installed_version or 'unknown'} does not match {requested}",
                }
                continue
            result[registry_id] = {"state": "success", "message": installed_version}
        return result

    async def queue_status(self, client_id: str | None = None) -> dict[str, Any]:
        detected = await self._require_compatible()
        url = f"{self.origin}/v2/manager/queue/status" if detected[0] == "v2" else f"{self.origin}/manager/queue/status"
        if detected[0] == "v2" and client_id:
            url += f"?client_id={client_id}"
        async with aiohttp.ClientSession(trust_env=True, timeout=aiohttp.ClientTimeout(total=10)) as session:
            async with session.get(url) as response:
                if response.status != 200:
                    raise UserFacingError("dependencies.manager_request_failed", {"status": response.status})
                data = await response.json()
        if not isinstance(data, dict):
            raise UserFacingError("dependencies.manager_request_failed", {"status": 0, "detail": "invalid queue status response"})
        done = int(data.get("done_count") or 0)
        in_progress = int(data.get("in_progress_count") or 0)
        total = done + in_progress + int(data.get("pending_count") or 0) if detected[0] == "v2" else int(data.get("total_count") or 0)
        return {"api": detected[0], "total": total, "done": done, "in_progress": in_progress, "processing": bool(data.get("is_processing"))}

    async def queue_history(self, client_id: str) -> dict[str, dict[str, Any]]:
        detected = await self._detect()
        if detected is None or not _manager_compatible(*detected) or detected[0] != "v2":
            return {}
        async with aiohttp.ClientSession(trust_env=True, timeout=aiohttp.ClientTimeout(total=10)) as session:
            async with session.get(f"{self.origin}/v2/manager/queue/history?client_id={client_id}") as response:
                if response.status != 200:
                    raise UserFacingError("dependencies.manager_request_failed", {"status": response.status})
                data = await response.json()
        if not isinstance(data, dict):
            raise UserFacingError("dependencies.manager_request_failed", {"status": 0, "detail": "invalid queue history response"})
        history = data.get("history")
        if not isinstance(history, (dict, list)):
            raise UserFacingError("dependencies.manager_request_failed", {"status": 0, "detail": "invalid queue history response"})
        entries = history.items() if isinstance(history, dict) else enumerate(history)
        result: dict[str, dict[str, Any]] = {}
        for task_id, item in entries:
            if not isinstance(item, dict):
                continue
            status = item.get("status") if isinstance(item.get("status"), dict) else {}
            outcome = str(
                status.get("status_str")
                or item.get("outcome")
                or (item.get("status") if isinstance(item.get("status"), str) else "")
            ).casefold()
            message = item.get("result") or item.get("message") or ""
            result[str(item.get("ui_id") or item.get("task_id") or task_id)] = {
                "outcome": "success" if outcome in {"success", "succeeded", "completed", "skipped", "skip"} else "failed",
                "message": str(message),
            }
        return result


def local_manager_status() -> dict[str, Any]:
    try:
        try:
            from comfyui_manager.glob import manager_core
        except ImportError:
            try:
                from comfyui_manager.legacy import manager_core
            except ImportError:
                import manager_core
        version = str(manager_core.version_str)
        numbers = _parse_version(version)
        compatible = bool(numbers) and (numbers[0] == 3 or numbers >= (4, 2, 1))
        return {"available": True, "compatible": compatible, "version": version}
    except Exception:
        return {"available": False, "compatible": False}
