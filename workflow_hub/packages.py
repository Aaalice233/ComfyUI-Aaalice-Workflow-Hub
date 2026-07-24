from __future__ import annotations

import hashlib
import json
import os
import stat
import tempfile
import zipfile
from pathlib import Path
from typing import Any

from .security import ensure_within, safe_filename, validate_zip_name

MAX_PACKAGE = 256 * 1024 * 1024
MAX_ENTRY = 64 * 1024 * 1024
MAX_EXPANDED = 512 * 1024 * 1024
ALLOWED = {"manifest.json", "workflow.json", "README.md", "CHANGELOG.md", "preview.png", "preview.webp"}
REQUIRED = {"manifest.json", "workflow.json", "CHANGELOG.md"}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def inspect_package(path: Path, expected_sha256: str | None = None) -> dict[str, Any]:
    if not path.is_file() or path.stat().st_size > MAX_PACKAGE:
        raise ValueError("工作流包不存在或超过 256 MiB")
    digest = sha256_file(path)
    if expected_sha256 and digest != expected_sha256:
        raise ValueError("工作流包 SHA-256 不一致")
    with zipfile.ZipFile(path) as archive:
        names: set[str] = set()
        total = 0
        for item in archive.infolist():
            name = validate_zip_name(item.filename)
            if name not in ALLOWED or item.is_dir():
                raise ValueError(f"包内不允许文件: {name}")
            mode = item.external_attr >> 16
            if stat.S_ISLNK(mode):
                raise ValueError(f"包内不允许符号链接: {name}")
            if item.file_size > MAX_ENTRY:
                raise ValueError(f"包内文件超过限制: {name}")
            total += item.file_size
            if total > MAX_EXPANDED or (item.compress_size and item.file_size / item.compress_size > 200):
                raise ValueError("工作流包解压体积或压缩比超过限制")
            names.add(name)
        if not REQUIRED.issubset(names):
            raise ValueError(f"工作流包缺少必需文件: {', '.join(sorted(REQUIRED - names))}")
        if {"preview.png", "preview.webp"}.issubset(names):
            raise ValueError("预览图最多一个")
        manifest = json.loads(archive.read("manifest.json"))
        workflow = json.loads(archive.read("workflow.json"))
    return {"sha256": digest, "size": path.stat().st_size, "manifest": manifest, "workflow": workflow}


def build_package(
    destination: Path,
    manifest: dict[str, Any],
    workflow: dict[str, Any],
    changelog: str,
    readme: str | None = None,
    preview: Path | None = None,
) -> dict[str, Any]:
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temp_name = tempfile.mkstemp(prefix=".workflow-hub-", suffix=".zip", dir=destination.parent)
    os.close(descriptor)
    try:
        with zipfile.ZipFile(temp_name, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
            archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
            archive.writestr("workflow.json", json.dumps(workflow, ensure_ascii=False, separators=(",", ":")))
            archive.writestr("CHANGELOG.md", changelog)
            if readme:
                archive.writestr("README.md", readme)
            if preview:
                suffix = preview.suffix.lower()
                if suffix not in {".png", ".webp"}:
                    raise ValueError("预览图必须是 PNG 或 WebP")
                archive.write(preview, f"preview{suffix}")
        os.replace(temp_name, destination)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)
    return inspect_package(destination)


def install_workflow(
    package_path: Path,
    workflows_root: Path,
    owner: str,
    repo: str,
    workflow_id: str,
    display_name: str,
    version: str,
    expected_sha256: str,
) -> tuple[Path, str]:
    inspected = inspect_package(package_path, expected_sha256)
    directory = ensure_within(workflows_root, workflows_root / safe_filename(f"{owner}-{repo}") / workflow_id)
    directory.mkdir(parents=True, exist_ok=True)
    target = ensure_within(directory, directory / f"{safe_filename(display_name)}-v{version}.json")
    content = json.dumps(inspected["workflow"], ensure_ascii=False, indent=2) + "\n"
    content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
    if target.exists():
        if hashlib.sha256(target.read_bytes()).hexdigest() != content_hash:
            raise ValueError("同版本本地文件内容不一致，已拒绝覆盖")
        return target, content_hash
    descriptor, temp_name = tempfile.mkstemp(prefix=".workflow-", suffix=".tmp", dir=directory)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_name, target)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)
    return target, content_hash
