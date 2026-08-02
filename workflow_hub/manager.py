from __future__ import annotations

from dataclasses import asdict, dataclass
import re
from typing import Any

import aiohttp


_flavor_cache: dict[str, tuple[str, str]] = {}


def _parse_version_numbers(version: str) -> tuple[int, ...]:
    try:
        return tuple(int(part) for part in str(version).lstrip("Vv").split(".")[:3])
    except ValueError:
        return ()


def _is_compatible_version(numbers: tuple[int, ...]) -> bool:
    # Manager 3.x 只暴露 legacy REST 端点，4.2.1+ 才提供 v2 端点，两条 API 路径都受支持。
    if not numbers:
        return False
    if numbers[0] == 3:
        return True
    return numbers >= (4, 2, 1)


@dataclass
class DependencyAction:
    registry_id: str | None
    name: str
    requested: str | None
    installed: str | None
    action: str
    required: bool
    manual: bool
    warning: str | None = None


def _is_git_revision(value: str | None) -> bool:
    return bool(re.fullmatch(r"[a-f0-9]{7,40}", str(value or "").casefold()))


def _github_url(aux_id: str | None) -> str | None:
    value = str(aux_id or "").strip().strip("/")
    return f"https://github.com/{value}" if value.count("/") == 1 else None


def _public_dependency(item: dict[str, Any]) -> dict[str, Any]:
    registry_id = str(item.get("registry_id") or "").strip() or None
    aux_id = str(item.get("aux_id") or "").strip() or None
    installed_version = str(item.get("version") or "").strip() or None
    development = _is_git_revision(installed_version)
    return {
        "registry_id": registry_id,
        "name": str(item["name"]),
        # Git revisions are local development state, not installable Registry versions.
        "version": None if development else installed_version,
        "required": True,
        "manual": registry_id is None,
        "source_url": _github_url(aux_id),
        "installed_version": installed_version,
        "development": development,
        "install_source": "registry" if registry_id else ("github" if aux_id else "manual"),
    }


class ManagerAdapter:
    def __init__(self, origin: str):
        self.origin = origin.rstrip("/")

    async def _detect(self) -> tuple[str, str] | None:
        cached = _flavor_cache.get(self.origin)
        if cached is not None:
            return cached
        try:
            async with aiohttp.ClientSession() as session:
                for flavor, path in (("v2", "/v2/manager/version"), ("legacy", "/manager/version")):
                    try:
                        async with session.get(f"{self.origin}{path}", timeout=3) as response:
                            if response.status != 200:
                                continue
                            version = (await response.text()).strip().strip('"')
                            detected = (flavor, version)
                            _flavor_cache[self.origin] = detected
                            return detected
                    except Exception:
                        continue
        except Exception:
            pass
        return None

    async def status(self) -> dict[str, Any]:
        detected = await self._detect()
        if detected is None:
            return {"available": False, "compatible": False}
        flavor, version = detected
        return {"available": True, "compatible": True, "version": version, "api": flavor}

    async def installed(self) -> dict[str, dict[str, Any]]:
        detected = await self._detect()
        if detected is None:
            raise RuntimeError("ComfyUI-Manager 未提供兼容的已安装节点接口")
        path = "/v2/customnode/installed" if detected[0] == "v2" else "/customnode/installed"
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{self.origin}{path}") as response:
                if response.status != 200:
                    raise RuntimeError("ComfyUI-Manager 未提供兼容的已安装节点接口")
                data = await response.json()
        if isinstance(data, dict):
            result: dict[str, dict[str, Any]] = {}
            for module_name, item in data.items():
                if not isinstance(item, dict):
                    continue
                registry_id = str(item.get("cnr_id") or item.get("id") or "").strip() or None
                aux_id = str(item.get("aux_id") or "").strip() or None
                key = registry_id or (f"github:{aux_id}" if aux_id else f"module:{module_name}")
                result[key] = {
                    **item,
                    "key": key,
                    "id": registry_id or aux_id or module_name,
                    "registry_id": registry_id,
                    "aux_id": aux_id,
                    "name": module_name,
                    "version": item.get("version") or item.get("ver"),
                }
            return result
        return {
            str(item.get("id")): {
                **item,
                "key": str(item.get("id")),
                "registry_id": item.get("cnr_id") or item.get("id"),
                "aux_id": item.get("aux_id"),
                "name": str(item.get("name") or item.get("title") or item.get("id")),
                "version": item.get("version") or item.get("ver"),
            }
            for item in data
            if isinstance(item, dict) and item.get("id")
        }

    async def installed_dependencies(self) -> list[dict[str, Any]]:
        installed = await self.installed()
        dependencies = [_public_dependency(item) for item in installed.values()]
        dependencies.sort(key=lambda item: str(item["name"]).casefold())
        return dependencies

    async def plan(self, dependencies: list[dict[str, Any]]) -> list[dict[str, Any]]:
        try:
            installed = await self.installed()
        except Exception:
            installed = {}
        result: list[DependencyAction] = []
        requested_by_id: dict[str, set[str]] = {}
        for dependency in dependencies:
            if dependency.get("registry_id") and dependency.get("version"):
                requested_by_id.setdefault(str(dependency["registry_id"]), set()).add(str(dependency["version"]))
        for dependency in dependencies:
            registry_id = dependency.get("registry_id")
            requested = dependency.get("version")
            current = installed.get(registry_id or "")
            installed_version = current.get("version") if current else None
            if registry_id and len(requested_by_id.get(registry_id, set())) > 1:
                action, warning = "conflict", "多个工作流版本要求了互不相同的节点版本"
            elif dependency.get("manual") or not registry_id:
                action, warning = "manual", "该节点未映射到 Comfy Registry，需要手动处理"
            elif not installed_version:
                action, warning = "install", None
            elif not requested or installed_version == requested:
                action, warning = "keep", None
            else:
                from packaging.version import InvalidVersion, Version

                try:
                    action = "upgrade" if Version(installed_version) < Version(requested) else "newer"
                    warning = "本地版本更高，默认保留" if action == "newer" else None
                except InvalidVersion:
                    action, warning = "unknown", "无法可靠比较依赖版本"
            result.append(
                DependencyAction(
                    registry_id=registry_id,
                    name=dependency["name"],
                    requested=requested,
                    installed=installed_version,
                    action=action,
                    required=dependency.get("required", True),
                    manual=dependency.get("manual", False),
                    warning=warning,
                )
            )
        return [asdict(item) for item in result]

    async def execute(self, actions: list[dict[str, Any]], client_id: str) -> list[dict[str, Any]]:
        allowed = {"install", "upgrade", "downgrade"}
        detected = await self._detect()
        flavor = detected[0] if detected else "v2"
        queued: list[dict[str, Any]] = []
        async with aiohttp.ClientSession() as session:
            for item in actions:
                if item.get("action") not in allowed or not item.get("registry_id"):
                    continue
                target_version = item.get("requested") or "latest"
                if flavor == "legacy":
                    payload = {
                        "id": item["registry_id"],
                        "version": target_version,
                        "selected_version": target_version,
                        "skip_post_install": False,
                        "ui_id": item["registry_id"],
                        "channel": "default",
                        "mode": "cache",
                    }
                    request = session.post(f"{self.origin}/manager/queue/install", json=payload)
                else:
                    params = {
                        "id": item["registry_id"],
                        "version": target_version,
                        "selected_version": target_version,
                        "mode": "cache",
                        "channel": "default",
                        "skip_post_install": False,
                    }
                    payload = {"ui_id": item["registry_id"], "client_id": client_id, "kind": "install", "params": params}
                    request = session.post(f"{self.origin}/v2/manager/queue/task", json=payload)
                async with request as response:
                    if response.status not in (200, 201):
                        raise RuntimeError(f"Manager 拒绝依赖任务 {item['name']}: {await response.text()}")
                queued.append(item)
            if queued:
                if flavor == "legacy":
                    async with session.get(f"{self.origin}/manager/queue/start") as response:
                        if response.status not in (200, 201):
                            raise RuntimeError(f"Manager 无法启动依赖队列: {await response.text()}")
                else:
                    async with session.post(f"{self.origin}/v2/manager/queue/start", json={"client_id": client_id}) as response:
                        if response.status not in (200, 201):
                            raise RuntimeError(f"Manager 无法启动依赖队列: {await response.text()}")
        return queued


    async def queue_status(self, client_id: str | None = None) -> dict[str, Any]:
        detected = await self._detect()
        if detected is None:
            raise RuntimeError("ComfyUI-Manager 未提供兼容的队列状态接口")
        flavor, _ = detected
        url = f"{self.origin}/v2/manager/queue/status" if flavor == "v2" else f"{self.origin}/manager/queue/status"
        if flavor == "v2" and client_id:
            url += f"?client_id={client_id}"
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=5) as response:
                if response.status != 200:
                    raise RuntimeError(f"Manager 无法提供队列状态: {await response.text()}")
                data = await response.json()
        done = int(data.get("done_count") or 0)
        in_progress = int(data.get("in_progress_count") or 0)
        if flavor == "v2":
            # v2 的 total_count 只含等待和执行中的任务，已完成任务在 history 里单独计数。
            total = done + in_progress + int(data.get("pending_count") or 0)
        else:
            total = int(data.get("total_count") or 0)
        return {"api": flavor, "total": total, "done": done, "in_progress": in_progress, "processing": bool(data.get("is_processing"))}

    async def queue_history(self, client_id: str) -> dict[str, dict[str, Any]]:
        detected = await self._detect()
        if detected is None:
            raise RuntimeError("ComfyUI-Manager 未提供兼容的队列历史接口")
        if detected[0] != "v2":
            # legacy 的逐任务结果只通过 WebSocket 广播，REST 不提供。
            return {}
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{self.origin}/v2/manager/queue/history?client_id={client_id}", timeout=5) as response:
                if response.status != 200:
                    raise RuntimeError(f"Manager 无法提供队列历史: {await response.text()}")
                data = await response.json()
        history = data.get("history") if isinstance(data, dict) else None
        if not isinstance(history, dict):
            return {}
        result: dict[str, dict[str, Any]] = {}
        for task_id, item in history.items():
            if not isinstance(item, dict):
                continue
            status = item.get("status") if isinstance(item.get("status"), dict) else {}
            outcome = str(status.get("status_str") or "").casefold()
            result[str(item.get("ui_id") or task_id)] = {
                "outcome": "success" if outcome in {"success", "skipped", "skip"} else ("failed" if outcome else "unknown"),
                "message": str(item.get("result") or ""),
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
                # Manager 3.x 把 glob/ 加进 sys.path，core 以顶层模块形式存在。
                import manager_core
        version = str(manager_core.version_str)
        numbers = _parse_version_numbers(version)
        return {"available": True, "compatible": _is_compatible_version(numbers), "version": version}
    except Exception:
        return {"available": False, "compatible": False}
