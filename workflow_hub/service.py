from __future__ import annotations

import base64
import hashlib
import importlib
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from .assets import package_input_assets, scan_workflow_assets
from .catalog import (
    BundledInput,
    Catalog,
    ModelDependency,
    Preview,
    Repository,
    WorkflowProduct,
    WorkflowVersion,
    merge_product,
    normalize_version,
    prepare_publish_product,
    product_repository_path,
    version_repository_path,
)
from .github import BranchState, GitHubClient, GitHubError, GitTreeFile
from .operations import Operation
from .packages import build_package_files, install_workflow, read_package_files, write_package
from .repository import build_projection_files, build_repository_files
from .security import ensure_within, parse_public_repository, require_github_https, safe_filename
from .storage import UserStorage


def _folder_paths() -> Any:
    return importlib.import_module("folder_paths")


def validate_catalog_assets(catalog: Catalog) -> Catalog:
    for product in catalog.workflows:
        if product.cover:
            require_github_https(str(product.cover.url))
        for version in product.versions:
            require_github_https(str(version.package.url))
            if version.preview:
                require_github_https(str(version.preview.url))
    return catalog


async def list_subscriptions(storage: UserStorage) -> list[dict[str, Any]]:
    return await storage.read_json("subscriptions.json", [])


async def add_subscription(storage: UserStorage, repository_url: str) -> dict[str, Any]:
    owner, repo = parse_public_repository(repository_url)
    client = GitHubClient()
    remote = await client.get_catalog(owner, repo)
    if remote is None:
        raise ValueError("仓库根目录没有 workflow-catalog.json")
    catalog = validate_catalog_assets(Catalog.model_validate_json(remote.content))
    item = {
        "owner": owner,
        "repo": repo,
        "url": f"https://github.com/{owner}/{repo}",
        "etag": remote.etag,
        "refreshed_at": datetime.now(timezone.utc).isoformat(),
        "error": None,
    }
    (storage.cache_dir / f"{owner}-{repo}.json").write_bytes(remote.content)

    def mutate(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if any(value["owner"].casefold() == owner.casefold() and value["repo"].casefold() == repo.casefold() for value in items):
            raise ValueError("该订阅源已存在")
        return items + [item]

    await storage.update_json("subscriptions.json", [], mutate)
    return {**item, "catalog": catalog.model_dump(mode="json")}


async def refresh_subscription(storage: UserStorage, owner: str, repo: str) -> dict[str, Any]:
    subscriptions = await list_subscriptions(storage)
    current = next(
        (
            item
            for item in subscriptions
            if item["owner"].casefold() == owner.casefold() and item["repo"].casefold() == repo.casefold()
        ),
        None,
    )
    if current is None:
        raise ValueError("订阅源不存在")
    client = GitHubClient()
    remote = await client.get_catalog(owner, repo, current.get("etag"))
    if remote:
        validate_catalog_assets(Catalog.model_validate_json(remote.content))
        (storage.cache_dir / f"{owner}-{repo}.json").write_bytes(remote.content)
    refreshed_at = datetime.now(timezone.utc).isoformat()

    def mutate(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        for item in items:
            if item["owner"].casefold() == owner.casefold() and item["repo"].casefold() == repo.casefold():
                item["etag"] = remote.etag if remote else item.get("etag")
                item["refreshed_at"] = refreshed_at
                item["error"] = None
        return items

    await storage.update_json("subscriptions.json", [], mutate)
    return {"changed": remote is not None, "refreshed_at": refreshed_at}


def find_catalog_updates(previous: Catalog, current: Catalog, owner: str, repo: str) -> list[dict[str, str]]:
    previous_by_id = {product.id: product for product in previous.workflows}
    updates: list[dict[str, str]] = []
    for product in current.workflows:
        old_product = previous_by_id.get(product.id)
        if old_product is None or product.archived or not old_product.versions:
            continue
        old_latest = max(normalize_version(item.version) for item in old_product.versions)
        newer = [item for item in product.versions if normalize_version(item.version) > old_latest]
        if not newer:
            continue
        latest = max(newer, key=lambda item: normalize_version(item.version))
        updates.append(
            {
                "owner": owner,
                "repo": repo,
                "workflow_id": product.id,
                "name": product.name,
                "version": latest.version,
            }
        )
    return updates


def reveal_in_file_manager(target: Path) -> None:
    if not target.is_file():
        raise ValueError("本地工作流文件不存在")
    folder = str(target.parent)
    if sys.platform == "win32":
        os.startfile(folder)  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", folder])
    else:
        subprocess.Popen(["xdg-open", folder])


async def aggregate_catalog(storage: UserStorage) -> list[dict[str, Any]]:
    installed = await storage.read_json("installed.json", [])
    stale_records = [item for item in installed if not _installed_record_exists(storage, item)]
    if stale_records:
        installed = await storage.update_json(
            "installed.json",
            [],
            lambda items: [item for item in items if _installed_record_exists(storage, item)],
        )
    result: list[dict[str, Any]] = []
    for source in await list_subscriptions(storage):
        cache = storage.cache_dir / f"{source['owner']}-{source['repo']}.json"
        if not cache.exists():
            continue
        try:
            catalog = validate_catalog_assets(Catalog.model_validate_json(cache.read_bytes()))
        except (ValidationError, ValueError):
            continue
        for product in catalog.workflows:
            local = [
                item
                for item in installed
                if item["owner"] == source["owner"] and item["repo"] == source["repo"] and item["workflow_id"] == product.id
            ]
            result.append(
                {
                    **product.model_dump(mode="json"),
                    "source": {"owner": source["owner"], "repo": source["repo"]},
                    "downloaded_versions": [item["version"] for item in local],
                }
            )
    return result


def _installed_record_exists(storage: UserStorage, record: dict[str, Any]) -> bool:
    try:
        target = ensure_within(storage.workflows_root, Path(record["path"]))
        return target.is_file()
    except (KeyError, OSError, ValueError):
        return False


async def download_version(
    storage: UserStorage,
    owner: str,
    repo: str,
    product: WorkflowProduct,
    version: WorkflowVersion,
    operation: Operation,
) -> dict[str, Any]:
    require_github_https(str(version.package.url))
    descriptor, temp_name = tempfile.mkstemp(prefix="workflow-hub-", suffix=".zip")
    os.close(descriptor)
    temp_path = Path(temp_name)
    try:
        operation.stage = "downloading"
        await GitHubClient().download(str(version.package.url), temp_path, operation)
        operation.stage = "verifying"
        target, content_hash = install_workflow(
            temp_path,
            storage.workflows_root,
            owner,
            repo,
            product.id,
            product.name,
            version.version,
            version.package.sha256,
            Path(_folder_paths().get_input_directory()),
        )
        record = {
            "owner": owner,
            "repo": repo,
            "workflow_id": product.id,
            "name": product.name,
            "version": version.version,
            "package_sha256": version.package.sha256,
            "workflow_sha256": content_hash,
            "path": str(target),
            "downloaded_at": datetime.now(timezone.utc).isoformat(),
        }

        def mutate(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
            key = (owner, repo, product.id, version.version)
            rest = [
                item
                for item in items
                if (item["owner"], item["repo"], item["workflow_id"], item["version"]) != key
            ]
            return rest + [record]

        await storage.update_json("installed.json", [], mutate)
        operation.stage = "complete"
        operation.status = "success"
        operation.result = record
        return record
    finally:
        temp_path.unlink(missing_ok=True)


async def download_optional_lora(model: ModelDependency, operation: Operation) -> dict[str, Any]:
    if model.type != "loras":
        raise ValueError("仅支持下载 LoRA 类型的可选资源")
    require_github_https(str(model.source_url))
    roots = _folder_paths().get_folder_paths("loras")
    if not roots:
        raise ValueError("ComfyUI 未配置 LoRA 目录")
    root = Path(roots[0]).resolve()
    target = ensure_within(root, root / model.filename.replace("\\", "/"))
    if target.suffix.lower() not in {".safetensors", ".ckpt", ".pt", ".bin"}:
        raise ValueError("LoRA 文件扩展名不受支持")
    directory = target.parent
    directory.mkdir(parents=True, exist_ok=True)
    if target.exists():
        if model.sha256 and hashlib.sha256(target.read_bytes()).hexdigest() != model.sha256:
            raise ValueError("同名 LoRA 内容不一致，已拒绝覆盖")
        operation.stage = "complete"
        operation.status = "success"
        operation.result = {"path": str(target), "already_exists": True}
        return operation.result
    descriptor, temp_name = tempfile.mkstemp(prefix=".workflow-hub-lora-", suffix=".tmp", dir=directory)
    os.close(descriptor)
    temp_path = Path(temp_name)
    try:
        operation.stage = "downloading"
        await GitHubClient().download(str(model.source_url), temp_path, operation)
        operation.stage = "verifying"
        if model.sha256 and hashlib.sha256(temp_path.read_bytes()).hexdigest() != model.sha256:
            raise ValueError("LoRA SHA-256 不一致")
        os.replace(temp_path, target)
        operation.stage = "complete"
        operation.status = "success"
        operation.result = {"path": str(target), "already_exists": False}
        return operation.result
    finally:
        temp_path.unlink(missing_ok=True)


async def _catalog_at_state(
    client: GitHubClient,
    owner: str,
    repo: str,
    state: BranchState,
    repository: dict[str, Any],
) -> Catalog:
    payload = await client.read_file_from_state(owner, repo, state, "workflow-catalog.json")
    if payload is None:
        if any(path == "workflows" or path.startswith("workflows/") for path in state.files):
            raise ValueError("仓库已有 workflows 目录但缺少工作流清单，已拒绝覆盖")
        return Catalog(repository=Repository.model_validate(repository), workflows=[])
    return validate_catalog_assets(Catalog.model_validate_json(payload))


def _relocation_changes(
    state: BranchState,
    old_path: str | None,
    new_path: str,
    writes: dict[str, bytes],
) -> tuple[set[str], dict[str, GitTreeFile]]:
    old_prefix = f"{old_path}/" if old_path else None
    new_prefix = f"{new_path}/"
    if old_path != new_path:
        occupied = [path for path in state.files if path.startswith(new_prefix)]
        if occupied:
            raise ValueError("目标类别下已经存在同名工作流目录")
    elif old_path is None and any(path.startswith(new_prefix) for path in state.files):
        raise ValueError("目标工作流目录已存在但未登记在清单中")
    if not old_prefix or old_path == new_path:
        return set(), {}
    delete_paths = {path for path in state.files if path.startswith(old_prefix)}
    copies: dict[str, GitTreeFile] = {}
    for path in delete_paths:
        target = f"{new_prefix}{path.removeprefix(old_prefix)}"
        if target not in writes:
            copies[target] = state.files[path]
    return delete_paths, copies


async def _commit_publication(
    client: GitHubClient,
    owner: str,
    repo: str,
    repository: dict[str, Any],
    incoming: WorkflowProduct,
    version_files: dict[str, bytes],
) -> WorkflowProduct:
    version = incoming.versions[0]
    for attempt in range(2):
        state = await client.get_branch_state(owner, repo)
        catalog = await _catalog_at_state(client, owner, repo, state, repository)
        existing = next((item for item in catalog.workflows if item.id == incoming.id), None)
        if existing and existing.repository_path != incoming.repository_path:
            raise ValueError("工作流名称或类别已被修改，请重新打开发布页后再发布")
        if existing:
            incoming = incoming.model_copy(
                update={
                    "name": existing.name,
                    "category": existing.category,
                    "summary": existing.summary,
                    "description": existing.description,
                    "tags": existing.tags,
                    "repository_path": existing.repository_path,
                    "cover": incoming.cover or existing.cover,
                }
            )
        if any(path.startswith(f"{version.repository_path}/") for path in state.files):
            raise ValueError(f"版本 {version.version} 的仓库目录已存在，禁止覆盖")
        merged = merge_product(catalog, incoming)
        product = next(item for item in merged.workflows if item.id == incoming.id)
        committed_version = next(
            item for item in product.versions if normalize_version(item.version) == normalize_version(version.version)
        )
        writes = build_repository_files(merged, product, committed_version, version_files)
        delete_paths, copies = _relocation_changes(
            state,
            existing.repository_path if existing else None,
            product.repository_path,
            writes,
        )
        try:
            await client.commit_files(
                owner,
                repo,
                state,
                writes,
                f"发布 {product.name} {committed_version.version}",
                delete_paths=delete_paths,
                copy_blobs=copies,
            )
            return product
        except GitHubError as exc:
            if attempt == 0 and exc.status in (409, 422):
                continue
            raise
    raise RuntimeError("仓库并发更新失败")


def _decode_preview(
    storage: UserStorage,
    tag: str,
    preview_data: dict[str, str] | None,
) -> tuple[Path | None, bytes | None]:
    if not preview_data:
        return None, None
    filename = str(preview_data.get("filename", "")).lower()
    suffix = Path(filename).suffix
    if suffix not in {".png", ".webp", ".jpg", ".jpeg"}:
        raise ValueError("项目封面必须是 PNG、WebP 或 JPEG")
    try:
        content = base64.b64decode(preview_data["data_base64"], validate=True)
    except Exception as exc:
        raise ValueError("项目封面数据无效") from exc
    if len(content) > 10 * 1024 * 1024:
        raise ValueError("项目封面不能超过 10 MiB")
    if suffix == ".png" and not content.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("项目封面内容不是有效 PNG")
    if suffix == ".webp" and not (content.startswith(b"RIFF") and content[8:12] == b"WEBP"):
        raise ValueError("项目封面内容不是有效 WebP")
    if suffix in {".jpg", ".jpeg"} and not content.startswith(b"\xff\xd8\xff"):
        raise ValueError("项目封面内容不是有效 JPEG")
    path = storage.drafts_dir / f"{tag}-cover{suffix}"
    path.write_bytes(content)
    return path, content


async def publish(
    storage: UserStorage,
    token: str,
    owner: str,
    repo: str,
    repository: dict[str, Any],
    product_data: dict[str, Any],
    workflow: dict[str, Any],
    operation: Operation,
    preview_data: dict[str, str] | None = None,
    selected_loras: list[str] | None = None,
) -> dict[str, Any]:
    client = GitHubClient(token)
    product = WorkflowProduct.model_validate(prepare_publish_product(product_data))
    if len(product.versions) != 1:
        raise ValueError("每次发布必须且只能包含一个版本")
    version = product.versions[0]
    operation.stage = "validating"
    state = await client.get_branch_state(owner, repo)
    catalog = await _catalog_at_state(client, owner, repo, state, repository)
    merge_product(catalog, product)

    images, detected_loras = scan_workflow_assets(workflow)
    unavailable_images = [item for item in images if item.status != "ready"]
    if unavailable_images:
        details = ", ".join(f"{item.name} ({item.status})" for item in unavailable_images)
        raise ValueError(f"加载图像无法随工作流打包: {details}")
    bundled_inputs = package_input_assets(images)
    version.inputs = [
        BundledInput.model_validate({key: value for key, value in item.items() if key != "path"})
        for item in bundled_inputs
    ]
    selected_names = set(selected_loras or [])
    lora_by_name = {item.name: item for item in detected_loras}
    unknown_loras = selected_names - set(lora_by_name)
    if unknown_loras:
        raise ValueError(f"所选 LoRA 不在当前工作流中: {', '.join(sorted(unknown_loras))}")
    selected_assets = [lora_by_name[name] for name in selected_names]
    unavailable_loras = [item for item in selected_assets if item.status != "ready" or not item.path]
    if unavailable_loras:
        details = ", ".join(f"{item.name} ({item.status})" for item in unavailable_loras)
        raise ValueError(f"所选 LoRA 无法发布: {details}")

    tag = f"{product.id}-v{version.version}"
    for lora in selected_assets:
        assert lora.sha256 is not None
        key = ("loras", lora.filename)
        version.models = [item for item in version.models if (item.type, item.filename) != key]
        asset_name = safe_filename(f"{tag}-lora-{lora.sha256[:12]}-{Path(lora.filename).name}").replace(" ", "_")
        version.models.append(
            ModelDependency(
                name=lora.name,
                type="loras",
                filename=lora.filename,
                source_url=f"https://github.com/{owner}/{repo}/releases/download/{tag}/{asset_name}",
                sha256=lora.sha256,
            )
        )

    package_name = safe_filename(f"{product.name}-v{version.version}.zip").replace(" ", "_")
    draft_name = safe_filename(f"{tag}-{package_name}").replace(" ", "_")
    package_path = storage.drafts_dir / draft_name
    preview_path, preview_bytes = _decode_preview(storage, tag, preview_data)
    manifest = {
        "schema_version": 1,
        "workflow_id": product.id,
        "name": product.name,
        "version": version.version,
        "custom_nodes": [item.model_dump(mode="json") for item in version.custom_nodes],
        "models": [item.model_dump(mode="json") for item in version.models],
        "inputs": [{key: value for key, value in item.items() if key != "path"} for item in bundled_inputs],
    }
    version_files = build_package_files(
        manifest,
        workflow,
        version.changelog,
        preview=preview_path,
        input_assets=bundled_inputs,
    )
    built = write_package(package_path, version_files)

    operation.stage = "creating_release"
    release = await client.get_release_by_tag(owner, repo, tag)
    if release and not release.get("draft"):
        raise ValueError("该版本 Release 已存在，禁止覆盖")
    if not release:
        release = await client.create_draft_release(
            owner,
            repo,
            tag,
            f"{product.category} / {product.name} v{version.version}",
            version.changelog,
        )
    operation.stage = "uploading"
    asset = next((item for item in release.get("assets", []) if item["name"] == package_name), None)
    if not asset:
        asset = await client.upload_asset(release["upload_url"], package_name, package_path.read_bytes(), "application/zip")
    version.package.url = f"https://github.com/{owner}/{repo}/releases/download/{tag}/{package_name}"
    version.package.size = int(asset.get("size") or built["size"])
    digest = str(asset.get("digest") or "")
    version.package.sha256 = digest.removeprefix("sha256:") if digest.startswith("sha256:") else built["sha256"]
    for lora in selected_assets:
        assert lora.path is not None and lora.sha256 is not None
        asset_name = safe_filename(f"{tag}-lora-{lora.sha256[:12]}-{Path(lora.filename).name}").replace(" ", "_")
        if not next((item for item in release.get("assets", []) if item["name"] == asset_name), None):
            await client.upload_asset(
                release["upload_url"],
                asset_name,
                lora.path.read_bytes(),
                "application/octet-stream",
            )
    if preview_path and preview_bytes:
        if not next((item for item in release.get("assets", []) if item["name"] == preview_path.name), None):
            await client.upload_asset(
                release["upload_url"],
                preview_path.name,
                preview_bytes,
                {
                    ".png": "image/png",
                    ".webp": "image/webp",
                    ".jpg": "image/jpeg",
                    ".jpeg": "image/jpeg",
                }[preview_path.suffix],
            )
        preview = Preview.model_validate(
            {
                "url": f"https://github.com/{owner}/{repo}/releases/download/{tag}/{preview_path.name}",
                "sha256": hashlib.sha256(preview_bytes).hexdigest(),
            }
        )
        product.cover = preview
        version.preview = preview
    product.versions = [version]
    product = WorkflowProduct.model_validate(product.model_dump(mode="json"))
    operation.stage = "publishing_release"
    release = await client.publish_release(owner, repo, int(release["id"]))

    operation.stage = "updating_repository"
    try:
        committed = await _commit_publication(client, owner, repo, repository, product, version_files)
    except Exception:
        await _record_pending(
            storage,
            owner,
            repo,
            tag,
            repository,
            product,
            draft_name,
            str(release["html_url"]),
        )
        if preview_path:
            preview_path.unlink(missing_ok=True)
        raise
    await _clear_pending(storage, owner, repo, tag)
    package_path.unlink(missing_ok=True)
    if preview_path:
        preview_path.unlink(missing_ok=True)
    result = {
        "repository": f"{owner}/{repo}",
        "repository_path": committed.repository_path,
        "workflow_id": product.id,
        "version": version.version,
        "release_url": release["html_url"],
    }
    operation.stage = "complete"
    operation.status = "success"
    operation.result = result
    return result


async def resume_publication(
    storage: UserStorage,
    token: str,
    record: dict[str, Any],
    operation: Operation,
) -> dict[str, Any]:
    owner = str(record["owner"])
    repo = str(record["repo"])
    tag = str(record["tag"])
    product = WorkflowProduct.model_validate(record["product"])
    package_path = storage.drafts_dir / safe_filename(str(record["draft_name"]))
    version_files = read_package_files(package_path, product.versions[0].package.sha256)
    operation.stage = "updating_repository"
    committed = await _commit_publication(
        GitHubClient(token),
        owner,
        repo,
        record["repository"],
        product,
        version_files,
    )
    await _clear_pending(storage, owner, repo, tag)
    package_path.unlink(missing_ok=True)
    result = {
        "repository": f"{owner}/{repo}",
        "repository_path": committed.repository_path,
        "workflow_id": product.id,
        "version": product.versions[0].version,
        "release_url": record["release_url"],
    }
    operation.stage = "complete"
    operation.status = "success"
    operation.result = result
    return result


async def update_product(
    token: str,
    owner: str,
    repo: str,
    workflow_id: str,
    changes: dict[str, Any],
) -> dict[str, Any]:
    allowed = {"name", "category", "summary", "description", "tags", "archived"}
    if set(changes) - allowed:
        raise ValueError("只能修改名称、类别、简介、说明、标签和归档状态")
    client = GitHubClient(token)
    for attempt in range(2):
        state = await client.get_branch_state(owner, repo)
        catalog = await _catalog_at_state(client, owner, repo, state, {})
        index = next((i for i, item in enumerate(catalog.workflows) if item.id == workflow_id), None)
        if index is None:
            raise ValueError("工作流产品不存在")
        existing = catalog.workflows[index]
        payload = existing.model_dump(mode="json")
        payload.update(changes)
        new_path = product_repository_path(str(payload["category"]), str(payload["name"]))
        payload["repository_path"] = new_path
        for version in payload["versions"]:
            version["repository_path"] = version_repository_path(new_path, str(version["version"]))
        product = WorkflowProduct.model_validate(payload)
        items = list(catalog.workflows)
        items[index] = product
        updated = Catalog.model_validate(catalog.model_copy(update={"workflows": items}).model_dump(mode="json"))
        writes = build_projection_files(updated, product)
        delete_paths, copies = _relocation_changes(state, existing.repository_path, product.repository_path, writes)
        try:
            await client.commit_files(
                owner,
                repo,
                state,
                writes,
                f"更新 {product.name} 展示资料",
                delete_paths=delete_paths,
                copy_blobs=copies,
            )
            return product.model_dump(mode="json")
        except GitHubError as exc:
            if attempt == 0 and exc.status in (409, 422):
                continue
            raise
    raise RuntimeError("仓库并发更新失败")


async def _record_pending(
    storage: UserStorage,
    owner: str,
    repo: str,
    tag: str,
    repository: dict[str, Any],
    product: WorkflowProduct,
    draft_name: str,
    release_url: str,
) -> None:
    record = {
        "owner": owner,
        "repo": repo,
        "tag": tag,
        "repository": repository,
        "product": product.model_dump(mode="json"),
        "draft_name": draft_name,
        "release_url": release_url,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await storage.update_json(
        "pending_publications.json",
        [],
        lambda items: [item for item in items if (item["owner"], item["repo"], item["tag"]) != (owner, repo, tag)]
        + [record],
    )


async def _clear_pending(storage: UserStorage, owner: str, repo: str, tag: str) -> None:
    await storage.update_json(
        "pending_publications.json",
        [],
        lambda items: [item for item in items if (item["owner"], item["repo"], item["tag"]) != (owner, repo, tag)],
    )
