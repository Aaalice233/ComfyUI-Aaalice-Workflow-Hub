from __future__ import annotations

import hashlib
import json
import os
import stat
import tempfile
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any

from .security import ensure_within, safe_filename, validate_zip_name

MAX_PACKAGE = 256 * 1024 * 1024
MAX_ENTRY = 64 * 1024 * 1024
MAX_EXPANDED = 512 * 1024 * 1024
ALLOWED = {
    "manifest.json",
    "workflow.json",
    "README.md",
    "CHANGELOG.md",
    "preview.png",
    "preview.webp",
    "preview.jpg",
    "preview.jpeg",
}
REQUIRED = {"manifest.json", "workflow.json", "CHANGELOG.md"}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tif", ".tiff"}


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
            raw_name = item.filename
            input_parts = PurePosixPath(raw_name).parts
            if (
                raw_name.startswith("inputs/")
                and "\\" not in raw_name
                and len(input_parts) == 2
                and ".." not in input_parts
            ):
                validate_zip_name(input_parts[1])
                name = raw_name
            else:
                name = validate_zip_name(raw_name)
            if name in names:
                raise ValueError(f"包内不允许重复文件: {name}")
            bundled_input = name.startswith("inputs/") and Path(name).suffix.lower() in IMAGE_EXTENSIONS
            if (name not in ALLOWED and not bundled_input) or item.is_dir():
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
        declared = manifest.get("inputs", [])
        if not isinstance(declared, list):
            raise ValueError("manifest.inputs 必须是数组")
        declared_names = {str(item.get("archive", "")) for item in declared if isinstance(item, dict)}
        bundled_names = {name for name in names if name.startswith("inputs/")}
        if declared_names != bundled_names:
            raise ValueError("manifest.inputs 与包内图像不一致")
        for item in declared:
            if (
                not isinstance(item, dict)
                or not isinstance(item.get("source"), str)
                or not isinstance(item.get("sha256"), str)
                or not isinstance(item.get("size"), int)
            ):
                raise ValueError("manifest.inputs 条目无效")
            content = archive.read(item["archive"])
            if len(content) != item["size"] or hashlib.sha256(content).hexdigest() != item["sha256"]:
                raise ValueError(f"包内图像校验失败: {item['archive']}")
    return {"sha256": digest, "size": path.stat().st_size, "manifest": manifest, "workflow": workflow}


def build_package_files(
    manifest: dict[str, Any],
    workflow: dict[str, Any],
    changelog: str,
    readme: str | None = None,
    preview: Path | None = None,
    input_assets: list[dict[str, Any]] | None = None,
) -> dict[str, bytes]:
    files = {
        "manifest.json": (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode(),
        "workflow.json": json.dumps(workflow, ensure_ascii=False, separators=(",", ":")).encode(),
        "CHANGELOG.md": changelog.encode(),
    }
    if readme:
        files["README.md"] = readme.encode()
    if preview:
        suffix = preview.suffix.lower()
        if suffix not in {".png", ".webp", ".jpg", ".jpeg"}:
            raise ValueError("预览图必须是 PNG、WebP 或 JPEG")
        files[f"preview{suffix}"] = preview.read_bytes()
    for item in input_assets or []:
        archive_name = str(item["archive"])
        files.setdefault(archive_name, Path(item["path"]).read_bytes())
    return files


def write_package(destination: Path, files: dict[str, bytes]) -> dict[str, Any]:
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temp_name = tempfile.mkstemp(prefix=".workflow-hub-", suffix=".zip", dir=destination.parent)
    os.close(descriptor)
    try:
        with zipfile.ZipFile(temp_name, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
            for name, content in files.items():
                archive.writestr(name, content)
        os.replace(temp_name, destination)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)
    return inspect_package(destination)


def build_package(
    destination: Path,
    manifest: dict[str, Any],
    workflow: dict[str, Any],
    changelog: str,
    readme: str | None = None,
    preview: Path | None = None,
    input_assets: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return write_package(
        destination,
        build_package_files(manifest, workflow, changelog, readme, preview, input_assets),
    )


def read_package_files(path: Path, expected_sha256: str | None = None) -> dict[str, bytes]:
    inspect_package(path, expected_sha256)
    with zipfile.ZipFile(path) as archive:
        return {item.filename: archive.read(item.filename) for item in archive.infolist()}


def install_workflow(
    package_path: Path,
    workflows_root: Path,
    owner: str,
    repo: str,
    workflow_id: str,
    display_name: str,
    version: str,
    expected_sha256: str,
    input_root: Path | None = None,
) -> tuple[Path, str]:
    inspected = inspect_package(package_path, expected_sha256)
    directory = ensure_within(workflows_root, workflows_root / safe_filename(f"{owner}-{repo}") / workflow_id)
    directory.mkdir(parents=True, exist_ok=True)
    target = ensure_within(directory, directory / f"{safe_filename(display_name)}-v{version}.json")
    workflow = inspected["workflow"]
    inputs = inspected["manifest"].get("inputs", [])
    if inputs:
        if input_root is None:
            raise ValueError("工作流包包含输入图像，但 ComfyUI input 目录不可用")
        input_root = input_root.resolve()
        input_directory = ensure_within(
            input_root,
            input_root / "Workflow Hub" / safe_filename(f"{owner}-{repo}") / safe_filename(workflow_id),
        )
        input_directory.mkdir(parents=True, exist_ok=True)
        replacements: dict[str, str] = {}
        with zipfile.ZipFile(package_path) as archive:
            for item in inputs:
                filename = Path(str(item["archive"])).name
                image_target = ensure_within(input_directory, input_directory / filename)
                content_bytes = archive.read(str(item["archive"]))
                if image_target.exists() and hashlib.sha256(image_target.read_bytes()).hexdigest() != item["sha256"]:
                    raise ValueError(f"同名输入图像内容不一致，已拒绝覆盖: {filename}")
                if not image_target.exists():
                    image_target.write_bytes(content_bytes)
                relative = image_target.relative_to(input_root).as_posix()
                replacements[str(item["source"])] = relative
        _replace_load_image_references(workflow, replacements)
    content = json.dumps(workflow, ensure_ascii=False, indent=2) + "\n"
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


def _replace_load_image_references(workflow: dict[str, Any], replacements: dict[str, str]) -> None:
    nodes = workflow.get("nodes")
    if isinstance(nodes, list):
        for node in nodes:
            if not isinstance(node, dict) or node.get("type") != "LoadImage":
                continue
            values = node.get("widgets_values")
            if isinstance(values, list) and values and isinstance(values[0], str) and values[0] in replacements:
                values[0] = replacements[values[0]]
    for node in workflow.values():
        if not isinstance(node, dict) or node.get("class_type") != "LoadImage":
            continue
        inputs = node.get("inputs")
        if isinstance(inputs, dict) and isinstance(inputs.get("image"), str) and inputs["image"] in replacements:
            inputs["image"] = replacements[inputs["image"]]
