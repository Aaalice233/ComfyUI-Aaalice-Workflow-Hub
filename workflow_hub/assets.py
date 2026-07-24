from __future__ import annotations

import copy
import hashlib
import importlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .security import safe_filename

MAX_BUNDLED_FILE = 64 * 1024 * 1024
MAX_LORA_FILE = 256 * 1024 * 1024
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tif", ".tiff"}
LORA_EXTENSIONS = {".safetensors", ".ckpt", ".pt", ".bin"}
LORA_MANAGER_TYPES = {
    "Lora Loader (LoraManager)",
    "Lora Stacker (LoraManager)",
    "WanVideo Lora Select (LoraManager)",
    "Create Hook LoRA (LoraManager)",
}
LORA_TAG = re.compile(r"<lora:([^:>]+):[-\d.]+(?::[-\d.]+)?>", re.IGNORECASE)


@dataclass(frozen=True)
class LocalAsset:
    name: str
    filename: str
    path: Path | None
    node_ids: tuple[str, ...]
    status: str
    size: int | None = None
    sha256: str | None = None

    def public(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "filename": self.filename,
            "node_ids": list(self.node_ids),
            "status": self.status,
            "size": self.size,
            "sha256": self.sha256,
        }


def _hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _folder_paths() -> Any:
    return importlib.import_module("folder_paths")


def _ui_nodes(workflow: dict[str, Any]) -> list[dict[str, Any]]:
    nodes = workflow.get("nodes")
    return [item for item in nodes if isinstance(item, dict)] if isinstance(nodes, list) else []


def _api_nodes(workflow: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    return [
        (str(node_id), node)
        for node_id, node in workflow.items()
        if isinstance(node, dict) and isinstance(node.get("class_type"), str)
    ]


def _image_references(workflow: dict[str, Any]) -> dict[str, set[str]]:
    found: dict[str, set[str]] = {}
    for node in _ui_nodes(workflow):
        if node.get("type") != "LoadImage":
            continue
        values = node.get("widgets_values")
        name = values[0] if isinstance(values, list) and values and isinstance(values[0], str) else None
        if name:
            found.setdefault(name, set()).add(str(node.get("id", "?")))
    for node_id, node in _api_nodes(workflow):
        if node.get("class_type") != "LoadImage":
            continue
        inputs = node.get("inputs")
        name = inputs.get("image") if isinstance(inputs, dict) else None
        if isinstance(name, str) and name:
            found.setdefault(name, set()).add(node_id)
    return found


def _lora_references(workflow: dict[str, Any]) -> dict[str, set[str]]:
    found: dict[str, set[str]] = {}

    def collect(value: Any, node_id: str) -> None:
        if isinstance(value, str):
            for match in LORA_TAG.finditer(value):
                found.setdefault(match.group(1).strip(), set()).add(node_id)
        elif isinstance(value, list):
            for item in value:
                collect(item, node_id)
        elif isinstance(value, dict):
            for item in value.values():
                collect(item, node_id)

    for node in _ui_nodes(workflow):
        if node.get("type") in LORA_MANAGER_TYPES:
            collect(node.get("widgets_values"), str(node.get("id", "?")))
    for node_id, node in _api_nodes(workflow):
        if node.get("class_type") in LORA_MANAGER_TYPES:
            collect(node.get("inputs"), node_id)
    return found


def _resolve_image(name: str, node_ids: set[str]) -> LocalAsset:
    suffix = Path(name.split(" [", 1)[0]).suffix.lower()
    if suffix not in IMAGE_EXTENSIONS:
        return LocalAsset(name, name, None, tuple(sorted(node_ids)), "unsupported")
    try:
        path = Path(_folder_paths().get_annotated_filepath(name))
    except Exception:
        path = Path()
    if not path.is_file():
        return LocalAsset(name, name, None, tuple(sorted(node_ids)), "missing")
    size = path.stat().st_size
    if size > MAX_BUNDLED_FILE:
        return LocalAsset(name, path.name, path, tuple(sorted(node_ids)), "too_large", size=size)
    return LocalAsset(name, path.name, path, tuple(sorted(node_ids)), "ready", size=size, sha256=_hash(path))


def _lora_index() -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    exact: dict[str, list[str]] = {}
    basename: dict[str, list[str]] = {}
    for filename in _folder_paths().get_filename_list("loras"):
        normalized = Path(filename).with_suffix("").as_posix().casefold()
        exact.setdefault(normalized, []).append(filename)
        basename.setdefault(Path(normalized).name, []).append(filename)
    return exact, basename


def _resolve_lora(name: str, node_ids: set[str], exact: dict[str, list[str]], basename: dict[str, list[str]]) -> LocalAsset:
    key = Path(name.replace("\\", "/")).with_suffix("").as_posix().casefold()
    matches = exact.get(key, [])
    if not matches:
        matches = basename.get(Path(key).name, [])
    if len(matches) > 1:
        return LocalAsset(name, name, None, tuple(sorted(node_ids)), "ambiguous")
    if not matches:
        return LocalAsset(name, name, None, tuple(sorted(node_ids)), "missing")
    filename = matches[0]
    if Path(filename).suffix.lower() not in LORA_EXTENSIONS:
        return LocalAsset(name, filename, None, tuple(sorted(node_ids)), "unsupported")
    resolved = _folder_paths().get_full_path("loras", filename)
    path = Path(resolved) if resolved else Path()
    if not path.is_file():
        return LocalAsset(name, filename, None, tuple(sorted(node_ids)), "missing")
    size = path.stat().st_size
    if size > MAX_LORA_FILE:
        return LocalAsset(name, filename, path, tuple(sorted(node_ids)), "too_large", size=size)
    return LocalAsset(name, filename, path, tuple(sorted(node_ids)), "ready", size=size, sha256=_hash(path))


def scan_workflow_assets(workflow: dict[str, Any]) -> tuple[list[LocalAsset], list[LocalAsset]]:
    images = [_resolve_image(name, nodes) for name, nodes in _image_references(workflow).items()]
    exact, basename = _lora_index()
    loras = [_resolve_lora(name, nodes, exact, basename) for name, nodes in _lora_references(workflow).items()]
    return sorted(images, key=lambda item: item.name.casefold()), sorted(loras, key=lambda item: item.name.casefold())


def clear_lora_manager(workflow: dict[str, Any]) -> dict[str, Any]:
    cleaned = copy.deepcopy(workflow)

    def clear_value(value: Any) -> Any:
        if isinstance(value, str):
            return " ".join(LORA_TAG.sub("", value).split())
        if isinstance(value, list):
            if value and all(
                isinstance(item, dict) and "name" in item and ({"strength", "active", "strengthTwo"} & set(item))
                for item in value
            ):
                return []
            return [clear_value(item) for item in value]
        if isinstance(value, dict):
            return {key: clear_value(item) for key, item in value.items()}
        return value

    for node in _ui_nodes(cleaned):
        if node.get("type") in LORA_MANAGER_TYPES:
            node["widgets_values"] = clear_value(node.get("widgets_values"))
    for _, node in _api_nodes(cleaned):
        if node.get("class_type") in LORA_MANAGER_TYPES:
            node["inputs"] = clear_value(node.get("inputs"))
    return cleaned


def package_input_assets(images: list[LocalAsset]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for item in images:
        if item.status != "ready" or not item.path or not item.sha256 or item.size is None:
            raise ValueError(f"加载图像无法打包: {item.name} ({item.status})")
        archive = f"inputs/{item.sha256[:12]}-{safe_filename(item.path.name)}"
        result.append(
            {
                "source": item.name,
                "archive": archive,
                "path": item.path,
                "sha256": item.sha256,
                "size": item.size,
                "node_ids": list(item.node_ids),
            }
        )
    return result
