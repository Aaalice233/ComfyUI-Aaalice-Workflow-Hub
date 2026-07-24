from __future__ import annotations

import base64
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from .catalog import Catalog, Preview, Repository, WorkflowProduct, WorkflowVersion, merge_product, normalize_version
from .github import ContentFile, GitHubClient, GitHubError
from .operations import Operation
from .packages import build_package, install_workflow
from .security import parse_public_repository, require_github_https
from .storage import UserStorage


def validate_catalog_assets(catalog: Catalog) -> Catalog:
    for product in catalog.workflows:
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
) -> dict[str, Any]:
    client = GitHubClient(token)
    product = WorkflowProduct.model_validate(product_data)
    if len(product.versions) != 1:
        raise ValueError("每次发布必须且只能包含一个版本")
    version = product.versions[0]
    tag = f"{product.id}-v{version.version}"
    if version.release_tag != tag:
        raise ValueError(f"Release tag 必须是 {tag}")
    operation.stage = "validating"
    current = await client.get_catalog(owner, repo)
    if current:
        catalog = Catalog.model_validate_json(current.content)
    else:
        catalog = Catalog(repository=Repository.model_validate(repository), workflows=[])
        initial_payload = (catalog.model_dump_json(indent=2) + "\n").encode()
        try:
            initial_sha = await client.put_catalog(
                owner,
                repo,
                initial_payload,
                None,
                "初始化 Workflow Hub 目录",
            )
            current = ContentFile(content=initial_payload, sha=initial_sha, etag=None)
        except GitHubError as exc:
            if exc.status not in (409, 422):
                raise
            current = await client.get_catalog(owner, repo)
            if not current:
                raise
            catalog = Catalog.model_validate_json(current.content)
    merged = merge_product(catalog, product)
    package_name = f"{tag}.zip"
    package_path = storage.drafts_dir / package_name
    preview_path: Path | None = None
    preview_bytes: bytes | None = None
    if preview_data:
        filename = str(preview_data.get("filename", "")).lower()
        suffix = Path(filename).suffix
        if suffix not in {".png", ".webp"}:
            raise ValueError("预览图必须是 PNG 或 WebP")
        try:
            preview_bytes = base64.b64decode(preview_data["data_base64"], validate=True)
        except Exception as exc:
            raise ValueError("预览图数据无效") from exc
        if len(preview_bytes) > 1024 * 1024:
            raise ValueError("预览图不能超过 1 MiB")
        if suffix == ".png" and not preview_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
            raise ValueError("预览图内容不是有效 PNG")
        if suffix == ".webp" and not (preview_bytes.startswith(b"RIFF") and preview_bytes[8:12] == b"WEBP"):
            raise ValueError("预览图内容不是有效 WebP")
        preview_path = storage.drafts_dir / f"{tag}-preview{suffix}"
        preview_path.write_bytes(preview_bytes)
    manifest = {
        "schema_version": 1,
        "workflow_id": product.id,
        "name": product.name,
        "version": version.version,
        "custom_nodes": [item.model_dump(mode="json") for item in version.custom_nodes],
        "models": [item.model_dump(mode="json") for item in version.models],
    }
    built = build_package(package_path, manifest, workflow, version.changelog, preview=preview_path)
    operation.stage = "creating_release"
    release = await client.get_release_by_tag(owner, repo, tag)
    pending_match: dict[str, Any] | None = None
    if release and not release.get("draft"):
        pending = await storage.read_json("pending_publications.json", [])
        pending_match = next(
            (item for item in pending if item["owner"] == owner and item["repo"] == repo and item["tag"] == tag),
            None,
        )
        if not pending_match:
            raise ValueError("该版本 Release 已存在，禁止覆盖")
    if not release:
        release = await client.create_draft_release(owner, repo, tag, f"{product.name} {version.version}", version.changelog)
    if release.get("draft"):
        operation.stage = "uploading"
        asset = next((item for item in release.get("assets", []) if item["name"] == package_name), None)
        if not asset:
            asset = await client.upload_asset(release["upload_url"], package_name, package_path.read_bytes(), "application/zip")
        version.package.url = f"https://github.com/{owner}/{repo}/releases/download/{tag}/{package_name}"
        version.package.size = int(asset.get("size") or built["size"])
        digest = str(asset.get("digest") or "")
        version.package.sha256 = digest.removeprefix("sha256:") if digest.startswith("sha256:") else built["sha256"]
        if preview_path and preview_bytes:
            preview_asset = next((item for item in release.get("assets", []) if item["name"] == preview_path.name), None)
            if not preview_asset:
                preview_asset = await client.upload_asset(
                    release["upload_url"],
                    preview_path.name,
                    preview_bytes,
                    "image/png" if preview_path.suffix == ".png" else "image/webp",
                )
            version.preview = Preview.model_validate(
                {
                    "url": f"https://github.com/{owner}/{repo}/releases/download/{tag}/{preview_path.name}",
                    "sha256": hashlib.sha256(preview_bytes).hexdigest(),
                }
            )
        product.versions = [version]
        merged = merge_product(catalog, product)
        operation.stage = "publishing_release"
        release = await client.publish_release(owner, repo, release["id"])
    else:
        asset = next((item for item in release.get("assets", []) if item["name"] == package_name), None)
        if not asset:
            raise ValueError("待同步 Release 缺少预期工作流包")
        restored = WorkflowProduct.model_validate(pending_match["product"])
        version = restored.versions[0]
        version.package.url = f"https://github.com/{owner}/{repo}/releases/download/{tag}/{package_name}"
        version.package.size = asset["size"]
        product = restored
        product.versions = [version]
        merged = merge_product(catalog, product)
    operation.stage = "updating_catalog"
    payload = (merged.model_dump_json(indent=2) + "\n").encode()
    try:
        await client.put_catalog(owner, repo, payload, current.sha if current else None, f"发布 {product.name} {version.version}")
    except GitHubError as exc:
        if exc.status in (409, 422):
            latest = await client.get_catalog(owner, repo)
            latest_catalog = (
                Catalog.model_validate_json(latest.content)
                if latest
                else Catalog(repository=Repository.model_validate(repository), workflows=[])
            )
            merged = merge_product(latest_catalog, product)
            payload = (merged.model_dump_json(indent=2) + "\n").encode()
            try:
                await client.put_catalog(owner, repo, payload, latest.sha if latest else None, f"发布 {product.name} {version.version}")
            except Exception:
                await _record_pending(storage, owner, repo, tag, repository, product, workflow, preview_data)
                raise
        else:
            await _record_pending(storage, owner, repo, tag, repository, product, workflow, preview_data)
            raise
    await _clear_pending(storage, owner, repo, tag)
    result = {"repository": f"{owner}/{repo}", "workflow_id": product.id, "version": version.version, "release_url": release["html_url"]}
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
    allowed = {"name", "summary", "description", "tags", "archived"}
    if set(changes) - allowed:
        raise ValueError("只能修改名称、简介、说明、标签和归档状态")
    client = GitHubClient(token)
    for attempt in range(2):
        current = await client.get_catalog(owner, repo)
        if not current:
            raise ValueError("发布仓库没有工作流目录")
        catalog = Catalog.model_validate_json(current.content)
        index = next((i for i, item in enumerate(catalog.workflows) if item.id == workflow_id), None)
        if index is None:
            raise ValueError("工作流产品不存在")
        product = catalog.workflows[index].model_copy(update=changes)
        product = WorkflowProduct.model_validate(product.model_dump(mode="json"))
        items = list(catalog.workflows)
        items[index] = product
        updated = catalog.model_copy(update={"workflows": items})
        try:
            await client.put_catalog(
                owner,
                repo,
                (updated.model_dump_json(indent=2) + "\n").encode(),
                current.sha,
                f"更新 {product.name} 展示资料",
            )
            return product.model_dump(mode="json")
        except GitHubError as exc:
            if attempt == 0 and exc.status in (409, 422):
                continue
            raise
    raise RuntimeError("目录并发更新失败")


async def _record_pending(
    storage: UserStorage,
    owner: str,
    repo: str,
    tag: str,
    repository: dict[str, Any],
    product: WorkflowProduct,
    workflow: dict[str, Any],
    preview_data: dict[str, str] | None,
) -> None:
    record = {
        "owner": owner,
        "repo": repo,
        "tag": tag,
        "repository": repository,
        "product": product.model_dump(mode="json"),
        "workflow": workflow,
        "preview": preview_data,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await storage.update_json(
        "pending_publications.json",
        [],
        lambda items: [item for item in items if (item["owner"], item["repo"], item["tag"]) != (owner, repo, tag)] + [record],
    )


async def _clear_pending(storage: UserStorage, owner: str, repo: str, tag: str) -> None:
    await storage.update_json(
        "pending_publications.json",
        [],
        lambda items: [item for item in items if (item["owner"], item["repo"], item["tag"]) != (owner, repo, tag)],
    )
