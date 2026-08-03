from __future__ import annotations

import re
from typing import Any

from .security import parse_public_repository


_IGNORED_SOURCE_KEYS = frozenset({
    "https://github.com/ltdrdata/comfyui-manager",
    "https://github.com/aaalice233/comfyui-aaalice-workflow-hub",
})
_IGNORED_IDENTIFIERS = frozenset({
    "comfyui-manager",
    "comfyui-aaalice-workflow-hub",
})


def _normalise_identifier(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "-", str(value or "").casefold()).strip("-")


def _source_key(value: Any) -> str | None:
    text = str(value or "").strip()
    if text.startswith("git@github.com:"):
        text = f"https://github.com/{text.removeprefix('git@github.com:')}"
    elif text.startswith("ssh://git@github.com/"):
        text = f"https://github.com/{text.removeprefix('ssh://git@github.com/')}"
    text = text.removesuffix(".git")
    try:
        owner, repo = parse_public_repository(text)
    except ValueError:
        return None
    return f"https://github.com/{owner.casefold()}/{repo.casefold()}"


def is_ignored_dependency(item: dict[str, Any]) -> bool:
    if _source_key(item.get("source_url")) in _IGNORED_SOURCE_KEYS:
        return True
    return any(
        _normalise_identifier(item.get(field)) in _IGNORED_IDENTIFIERS
        for field in ("registry_id", "name", "module_name")
    )
