from __future__ import annotations

import errno
import hashlib
import json
import os
import re
import shutil
import stat
import tempfile
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any

from .errors import UserFacingError
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
FILENAME_SEPARATORS = {"-", "_"}


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
        if sum(1 for name in names if name.startswith("preview.")) > 1:
            raise ValueError("预览图最多一个")
        try:
            manifest = json.loads(archive.read("manifest.json"))
            workflow = json.loads(archive.read("workflow.json"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("工作流包中的 JSON 无效") from exc
        if not isinstance(manifest, dict) or not isinstance(workflow, dict):
            raise ValueError("工作流包的 manifest.json 和 workflow.json 必须是对象")
        declared = manifest.get("inputs", [])
        if not isinstance(declared, list):
            raise ValueError("manifest.inputs 必须是数组")
        declared_names = {
            item.get("archive")
            for item in declared
            if isinstance(item, dict) and isinstance(item.get("archive"), str)
        }
        bundled_names = {name for name in names if name.startswith("inputs/")}
        if declared_names != bundled_names:
            raise ValueError("manifest.inputs 与包内图像不一致")
        sources: set[str] = set()
        for item in declared:
            if (
                not isinstance(item, dict)
                or not isinstance(item.get("archive"), str)
                or item.get("archive") not in bundled_names
                or not isinstance(item.get("source"), str)
                or not isinstance(item.get("sha256"), str)
                or not re.fullmatch(r"[0-9a-f]{64}", item["sha256"])
                or not isinstance(item.get("size"), int)
                or item["size"] <= 0
                or item["size"] > MAX_ENTRY
            ):
                raise ValueError("manifest.inputs 条目无效")
            source_path = _input_relative_path(item["source"])
            source_key = os.path.normcase(source_path.as_posix())
            if source_key in sources:
                raise ValueError(f"manifest.inputs 不得重复声明图像: {item['source']}")
            sources.add(source_key)
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


def _input_relative_path(source: str) -> PurePosixPath:
    normalized = source.replace("\\", "/")
    path = PurePosixPath(normalized)
    if (
        not source.strip()
        or normalized.startswith("/")
        or normalized.endswith("/")
        or path.is_absolute()
        or not path.parts
        or any(part in {"", ".", ".."} or ":" in part for part in path.parts)
    ):
        raise ValueError(f"输入图像引用不是有效的相对路径: {source}")
    return path


def _install_new_file(temp_name: str, target: Path) -> bool:
    try:
        os.link(temp_name, target)
        return True
    except FileExistsError:
        return False
    except OSError as exc:
        unsupported = exc.errno in {errno.ENOTSUP, errno.EOPNOTSUPP} or getattr(exc, "winerror", None) in {1, 50}
        if not unsupported:
            raise

    # exFAT、网络盘和部分虚拟盘不支持硬链接，仍需保持不覆盖已有文件的约束。
    try:
        descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o666)
    except FileExistsError:
        return False
    try:
        with os.fdopen(descriptor, "wb") as destination, open(temp_name, "rb") as source:
            shutil.copyfileobj(source, destination)
            destination.flush()
            os.fsync(destination.fileno())
    except BaseException:
        target.unlink(missing_ok=True)
        raise
    return True


def install_workflow(
    package_path: Path,
    workflows_root: Path,
    display_name: str,
    version: str,
    expected_sha256: str,
    input_root: Path | None = None,
    *,
    inspected: dict[str, Any] | None = None,
) -> tuple[Path, str]:
    inspected = inspected or inspect_package(package_path, expected_sha256)
    workflows_root = workflows_root.resolve()
    workflows_root.mkdir(parents=True, exist_ok=True)
    separator = inspected["manifest"].get("filename_separator", "-")
    if separator not in FILENAME_SEPARATORS:
        separator = "-"
    target = ensure_within(
        workflows_root,
        workflows_root / f"{safe_filename(display_name)}{separator}v{safe_filename(version)}.json",
    )
    inputs = inspected["manifest"].get("inputs", [])
    pending_inputs: list[tuple[Path, bytes, str]] = []
    if inputs:
        if input_root is None:
            raise ValueError("工作流包包含输入图像，但 ComfyUI input 目录不可用")
        input_root = input_root.resolve()
        input_root.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(package_path) as archive:
            for item in inputs:
                relative = _input_relative_path(str(item["source"]))
                image_target = ensure_within(input_root, input_root.joinpath(*relative.parts))
                content_bytes = archive.read(str(item["archive"]))
                if image_target.exists():
                    if not image_target.is_file() or hashlib.sha256(image_target.read_bytes()).hexdigest() != item["sha256"]:
                        raise UserFacingError("subscription.input_file_conflict", {"path": relative.as_posix()})
                else:
                    pending_inputs.append((image_target, content_bytes, relative.as_posix()))
    content = json.dumps(inspected["workflow"], ensure_ascii=False, indent=2) + "\n"
    content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()

    def write_pending_inputs() -> list[Path]:
        created: list[Path] = []
        try:
            for image_target, content_bytes, relative in pending_inputs:
                image_target.parent.mkdir(parents=True, exist_ok=True)
                descriptor, temp_name = tempfile.mkstemp(prefix=".input-", suffix=".tmp", dir=image_target.parent)
                try:
                    with os.fdopen(descriptor, "wb") as stream:
                        stream.write(content_bytes)
                        stream.flush()
                        os.fsync(stream.fileno())
                    if _install_new_file(temp_name, image_target):
                        created.append(image_target)
                    elif (
                        not image_target.is_file()
                        or hashlib.sha256(image_target.read_bytes()).hexdigest()
                        != hashlib.sha256(content_bytes).hexdigest()
                    ):
                        raise UserFacingError("subscription.input_file_conflict", {"path": relative})
                finally:
                    if os.path.exists(temp_name):
                        os.unlink(temp_name)
        except BaseException:
            for image_target in created:
                image_target.unlink(missing_ok=True)
            raise
        return created

    if target.exists():
        if not target.is_file() or hashlib.sha256(target.read_bytes()).hexdigest() != content_hash:
            raise UserFacingError("subscription.workflow_file_conflict", {"path": target.name})
        write_pending_inputs()
        return target, content_hash
    created_inputs = write_pending_inputs()
    temp_name = ""
    try:
        descriptor, temp_name = tempfile.mkstemp(prefix=".workflow-", suffix=".tmp", dir=workflows_root)
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        if not _install_new_file(temp_name, target):
            if not target.is_file() or hashlib.sha256(target.read_bytes()).hexdigest() != content_hash:
                raise UserFacingError("subscription.workflow_file_conflict", {"path": target.name})
    except BaseException:
        for image_target in created_inputs:
            image_target.unlink(missing_ok=True)
        raise
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)
    return target, content_hash
