from __future__ import annotations

from copy import deepcopy
from importlib import import_module
import re
from typing import Any


COMFYUI_VERSION_PATTERN = re.compile(r"^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$")


def current_comfyui_version() -> str:
    try:
        module = import_module("comfyui_version")
    except ImportError as exc:
        raise RuntimeError("无法检测当前 ComfyUI 内核版本") from exc
    version = str(getattr(module, "__version__", "")).strip()
    if not COMFYUI_VERSION_PATTERN.fullmatch(version):
        raise RuntimeError(f"无法识别当前 ComfyUI 内核版本：{version or '空值'}")
    return version


def stamp_product_comfyui_version(product: dict[str, Any], version: str | None = None) -> dict[str, Any]:
    detected = version or current_comfyui_version()
    stamped = deepcopy(product)
    versions = stamped.get("versions")
    if not isinstance(versions, list) or not versions:
        raise ValueError("发布内容缺少工作流版本")
    for item in versions:
        if not isinstance(item, dict):
            raise ValueError("工作流版本必须是对象")
        item["comfyui"] = {"minimum": detected, "maximum": detected}
    return stamped
