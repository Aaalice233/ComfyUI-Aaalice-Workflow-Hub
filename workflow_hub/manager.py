from __future__ import annotations

from dataclasses import asdict, dataclass
import re
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


def _normalized_identifier(value: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", "-", str(value or "").casefold()).strip("-")


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


def resolve_workflow_dependencies(
    node_types: set[str],
    mappings: dict[str, Any],
    object_info: dict[str, Any],
    installed: dict[str, dict[str, Any]],
) -> tuple[list[dict[str, Any]], str, list[str]]:
    installed_items = list(installed.values())

    def find_installed(identifier: str | None) -> dict[str, Any] | None:
        normalized = _normalized_identifier(identifier)
        for item in installed_items:
            candidates = {
                _normalized_identifier(item.get("registry_id")),
                _normalized_identifier(item.get("aux_id")),
                _normalized_identifier(item.get("name")),
                _normalized_identifier(str(item.get("aux_id") or "").split("/")[-1]),
            }
            if normalized and normalized in candidates:
                return item
        return None

    dependencies: list[dict[str, Any]] = []
    matched_install_keys: set[str] = set()
    remaining = set(node_types)

    def append_installed(item: dict[str, Any]) -> None:
        key = str(item.get("key") or item.get("registry_id") or item.get("aux_id") or item["name"])
        if key in matched_install_keys:
            return
        matched_install_keys.add(key)
        dependencies.append(_public_dependency(item))

    for mapping_id, value in mappings.items():
        if not isinstance(value, list) or not value or not isinstance(value[0], list):
            continue
        matched = sorted(remaining.intersection(str(node) for node in value[0]))
        if not matched:
            continue
        local = find_installed(str(mapping_id))
        if local is None and len(value) > 1 and isinstance(value[1], dict):
            local = find_installed(str(value[1].get("title_aux") or ""))
        if local is None:
            continue
        remaining.difference_update(matched)
        append_installed(local)

    unresolved: list[str] = []
    for node_type in sorted(remaining):
        info = object_info.get(node_type)
        if not isinstance(info, dict):
            unresolved.append(node_type)
            continue
        module = str(info.get("python_module") or "")
        if module and not module.startswith("custom_nodes."):
            continue
        local = find_installed(module.split(".", 1)[-1] if module else None)
        if local is None:
            unresolved.append(node_type)
            continue
        append_installed(local)

    if unresolved:
        fallback = [_public_dependency(item) for item in installed_items if item.get("enabled", True)]
        fallback.sort(key=lambda item: str(item["name"]).casefold())
        return fallback, "installed_fallback", unresolved
    dependencies.sort(key=lambda item: str(item["name"]).casefold())
    return dependencies, "workflow", []


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
            }
            for item in data
            if isinstance(item, dict) and item.get("id")
        }

    async def scan(self, workflow: dict[str, Any]) -> dict[str, Any]:
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
        installed = await self.installed()
        mappings: dict[str, Any] = {}
        object_info: dict[str, Any] = {}
        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(f"{self.origin}/v2/customnode/getmappings?mode=local", timeout=10) as response:
                    data = await response.json() if response.status == 200 else {}
                    if isinstance(data, dict):
                        mappings = data
            except (aiohttp.ClientError, TimeoutError, ValueError):
                # The installed-list fallback remains useful when Manager cannot expose mappings.
                pass
            try:
                async with session.get(f"{self.origin}/object_info", timeout=10) as response:
                    data = await response.json() if response.status == 200 else {}
                    if isinstance(data, dict):
                        object_info = data
            except (aiohttp.ClientError, TimeoutError, ValueError):
                # Missing object metadata is represented by unresolved nodes below.
                pass
        dependencies, mode, unresolved = resolve_workflow_dependencies(node_types, mappings, object_info, installed)
        return {"items": dependencies, "mode": mode, "unresolved_nodes": unresolved}

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
