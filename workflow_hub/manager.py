from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

import aiohttp


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


class ManagerAdapter:
    def __init__(self, origin: str):
        self.origin = origin.rstrip("/")

    async def status(self) -> dict[str, Any]:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(f"{self.origin}/v2/manager/version", timeout=3) as response:
                    if response.status != 200:
                        return {"available": False, "compatible": False}
                    text = await response.text()
                    return {"available": True, "compatible": True, "version": text.strip('"')}
        except Exception:
            return {"available": False, "compatible": False}

    async def installed(self) -> dict[str, dict[str, Any]]:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{self.origin}/v2/customnode/installed") as response:
                if response.status != 200:
                    raise RuntimeError("ComfyUI-Manager 未提供兼容的已安装节点接口")
                data = await response.json()
        if isinstance(data, dict):
            result: dict[str, dict[str, Any]] = {}
            for module_name, item in data.items():
                if not isinstance(item, dict):
                    continue
                registry_id = item.get("cnr_id") or item.get("id")
                if registry_id:
                    result[str(registry_id)] = {
                        **item,
                        "id": registry_id,
                        "name": module_name,
                        "version": item.get("version") or item.get("ver"),
                    }
            return result
        return {str(item.get("id")): item for item in data if isinstance(item, dict) and item.get("id")}

    async def scan(self, workflow: dict[str, Any]) -> list[dict[str, Any]]:
        node_types: set[str] = set()

        def walk(value: Any) -> None:
            if isinstance(value, dict):
                nodes = value.get("nodes")
                if isinstance(nodes, list):
                    for node in nodes:
                        if isinstance(node, dict) and isinstance(node.get("type"), str):
                            node_types.add(node["type"])
                for child in value.values():
                    walk(child)
            elif isinstance(value, list):
                for child in value:
                    walk(child)

        walk(workflow)
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{self.origin}/v2/customnode/getmappings?mode=local") as response:
                if response.status != 200:
                    raise RuntimeError("ComfyUI-Manager 未提供兼容的节点映射接口")
                mappings = await response.json()
            async with session.get(f"{self.origin}/object_info") as response:
                object_info = await response.json() if response.status == 200 else {}
        installed = await self.installed()
        dependencies: list[dict[str, Any]] = []
        remaining = set(node_types)
        for registry_id, value in mappings.items():
            if not isinstance(value, list) or not value or not isinstance(value[0], list):
                continue
            matched = sorted(remaining.intersection(str(item) for item in value[0]))
            if not matched:
                continue
            remaining.difference_update(matched)
            local = installed.get(registry_id, {})
            dependencies.append(
                {
                    "registry_id": registry_id,
                    "name": local.get("name") or registry_id,
                    "version": local.get("version"),
                    "required": True,
                    "manual": False,
                    "source_url": None,
                }
            )
        manual_nodes = []
        for node_type in sorted(remaining):
            module = str(object_info.get(node_type, {}).get("python_module", ""))
            if module and not module.startswith("custom_nodes."):
                continue
            manual_nodes.append(node_type)
        for node_type in manual_nodes:
            dependencies.append(
                {
                    "registry_id": None,
                    "name": node_type,
                    "version": None,
                    "required": True,
                    "manual": True,
                    "source_url": None,
                }
            )
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
        queued: list[dict[str, Any]] = []
        async with aiohttp.ClientSession() as session:
            for item in actions:
                if item.get("action") not in allowed or not item.get("registry_id"):
                    continue
                target_version = item.get("requested") or "latest"
                params = {
                    "id": item["registry_id"],
                    "version": target_version,
                    "selected_version": target_version,
                    "mode": "cache",
                    "channel": "default",
                    "skip_post_install": False,
                }
                payload = {"ui_id": item["registry_id"], "client_id": client_id, "kind": "install", "params": params}
                async with session.post(f"{self.origin}/v2/manager/queue/task", json=payload) as response:
                    if response.status not in (200, 201):
                        raise RuntimeError(f"Manager 拒绝依赖任务 {item['name']}: {await response.text()}")
                queued.append(item)
            if queued:
                async with session.post(f"{self.origin}/v2/manager/queue/start", json={"client_id": client_id}) as response:
                    if response.status not in (200, 201):
                        raise RuntimeError(f"Manager 无法启动依赖队列: {await response.text()}")
        return queued


def local_manager_status() -> dict[str, Any]:
    try:
        try:
            from comfyui_manager.glob import manager_core
        except ImportError:
            from comfyui_manager.legacy import manager_core
        version = str(manager_core.version_str)
        numbers = tuple(int(part) for part in version.lstrip("Vv").split(".")[:3])
        return {"available": True, "compatible": numbers >= (4, 2, 1), "version": version}
    except Exception:
        return {"available": False, "compatible": False}
