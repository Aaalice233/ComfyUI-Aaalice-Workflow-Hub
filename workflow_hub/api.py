from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, Awaitable, Callable, TypeVar
from urllib.parse import urlparse

from aiohttp import web
from pydantic import ValidationError

from .assets import scan_workflow_assets
from .catalog import Catalog, WorkflowProduct, prepare_publish_product
from .compatibility import current_comfyui_version, stamp_product_comfyui_version
from .errors import UserFacingError
from .github import CLIENT_ID, GitHubClient, GitHubError, poll_device_flow, refresh_access_token, start_device_flow, tokens
from .legacy_manager import ManagerAdapter, local_manager_status
from .manager import GitAdapter, local_git_status
from .operations import Operation, operations
from .security import ensure_within, parse_public_repository
from .service import (
    add_subscription,
    aggregate_catalog,
    delete_version,
    delete_workflow,
    download_optional_lora,
    download_version,
    find_catalog_updates,
    list_managed_products,
    list_subscriptions,
    publish,
    refresh_subscription,
    resume_publication,
    reveal_in_file_manager,
    update_product,
    update_version_changelog,
)
from .storage import UserStorage

BASE = "/workflow-hub/api/v1"
ROOT = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "web" / "app"
MAX_JSON = 20 * 1024 * 1024
_registered = False
_startup_refresh_tasks: dict[str, asyncio.Task[list[dict[str, str]]]] = {}
_startup_notifications_delivered: set[str] = set()


async def _json(request: web.Request) -> dict[str, Any]:
    origin = request.headers.get("Origin")
    if origin:
        parsed = urlparse(origin)
        if parsed.netloc.casefold() != request.host.casefold() or parsed.scheme != request.scheme:
            raise ValueError("拒绝跨来源写请求")
    if request.content_length and request.content_length > MAX_JSON:
        raise ValueError("请求体超过 20 MiB")
    raw = await request.read()
    if len(raw) > MAX_JSON:
        raise ValueError("请求体超过 20 MiB")
    if raw and request.content_type != "application/json":
        raise ValueError("JSON 请求体必须使用 application/json")
    data = json.loads(raw or b"{}")
    if not isinstance(data, dict):
        raise ValueError("请求体必须是 JSON 对象")
    return data


def _response_error(exc: Exception) -> web.Response:
    if isinstance(exc, UserFacingError):
        return web.json_response({"error_code": exc.code, "error_params": exc.params}, status=400)
    if isinstance(exc, ValidationError):
        return web.json_response({"error": "数据校验失败", "details": exc.errors(include_url=False)}, status=400)
    if isinstance(exc, GitHubError):
        # 401 原样透传 HTTP 状态，前端据此把界面降级为未登录。
        status = 401 if exc.status == 401 else (502 if exc.status >= 500 or exc.status == 0 else 400)
        return web.json_response({"error": str(exc), "github_status": exc.status}, status=status)
    if isinstance(exc, (ValueError, KeyError, json.JSONDecodeError)):
        return web.json_response({"error": str(exc).strip("'")}, status=400)
    return web.json_response({"error": str(exc) or exc.__class__.__name__}, status=500)


def endpoint(handler: Callable[[web.Request], Awaitable[web.StreamResponse]]) -> Callable[[web.Request], Awaitable[web.StreamResponse]]:
    async def wrapped(request: web.Request) -> web.StreamResponse:
        try:
            return await handler(request)
        except Exception as exc:
            return _response_error(exc)

    return wrapped


T = TypeVar("T")


async def _guarded_github_call(storage: UserStorage, action: Awaitable[T]) -> T:
    try:
        return await action
    except GitHubError as exc:
        if exc.status == 401:
            # 已存储的 token 被吊销或过期后，每次请求都只会重复 401；
            # 凭据已不可用，直接清除并提示重新登录，避免之后每次进页面都报错。
            await tokens.delete(storage.key)
            raise GitHubError("GitHub 登录已失效，请重新登录", 401) from exc
        raise


async def _run(operation: Operation, action: Awaitable[dict[str, Any]]) -> None:
    try:
        await action
    except UserFacingError as exc:
        operation.status = "failed"
        operation.stage = "failed"
        operation.error_code = exc.code
        operation.error_params = exc.params
    except Exception as exc:
        operation.status = "failed"
        operation.stage = "failed"
        operation.logs.append(str(exc))


_dependency_lock = asyncio.Lock()


async def _perform_dependency_operation(
    operation: Operation,
    actions: list[dict[str, Any]],
    manager_origin: str,
) -> None:
    executable = [item for item in actions if item.get("action") in {"install", "upgrade", "downgrade"}]
    manager_actions = [item for item in executable if item.get("registry_id") and not item.get("source_url")]
    git_actions = [item for item in executable if item not in manager_actions]
    operation.progress_mode = "tasks"
    operation.progress = {"received": 0, "total": len(executable)}
    results: list[dict[str, Any]] = []

    async def add_log(line: str) -> None:
        text = line.replace("\r", "").strip()
        if text:
            operation.logs.append(text)

    async def update_progress(done: int, total: int) -> None:
        operation.progress = {"received": done, "total": total}

    async def update_result(result: dict[str, Any]) -> None:
        if result not in results:
            results.append(result)
        operation.result = {"tasks": list(results)}
        if result.get("state") == "failed":
            code = result.get("error_code") or "dependencies.git_command_failed"
            params = result.get("error_params") or {}
            await add_log(f"{result.get('name', '')}: {code} {params}")

    try:
        operation.stage = "installing"
        completed = 0
        if manager_actions:
            manager = ManagerAdapter(manager_origin)
            await add_log("manager queue: submitting dependency tasks")
            queued = await manager.execute(manager_actions, operation.id)
            for item in queued:
                results.append({
                    "name": item.get("name", item.get("registry_id", "")),
                    "requested": item.get("requested"),
                    "action": item.get("action", "install"),
                    "state": "installing",
                    "registry_id": item.get("registry_id"),
                })
            operation.result = {"tasks": list(results)}
            await update_progress(0, len(executable))
            history_seen: set[str] = set()
            last_status: tuple[int, int, int, bool] | None = None
            for _ in range(1800):
                status = await manager.queue_status(operation.id)
                snapshot = (status["total"], status["done"], status["in_progress"], status["processing"])
                if snapshot != last_status:
                    await add_log(f"manager queue: total={snapshot[0]} done={snapshot[1]} in_progress={snapshot[2]} processing={snapshot[3]}")
                    last_status = snapshot
                history = await manager.queue_history(operation.id)
                await update_progress(max(completed, min(status["done"], len(manager_actions)), 0), len(executable))
                for item in results:
                    key = str(item.get("registry_id") or "")
                    outcome = history.get(key)
                    if not outcome or key in history_seen:
                        continue
                    history_seen.add(key)
                    item["state"] = outcome["outcome"]
                    item["message"] = outcome.get("message", "")
                    if item["state"] == "failed":
                        item["error_code"] = "dependencies.manager_task_failed"
                        item["error_params"] = {"name": item["name"]}
                    completed += 1
                    await update_result(item)
                    await update_progress(completed, len(executable))
                if completed >= len(manager_actions):
                    break
                if not status["processing"] and (status["total"] == 0 or status["done"] >= len(manager_actions)):
                    for item in results:
                        if item.get("state") == "installing":
                            item["state"] = "unknown"
                            await add_log(f"{item.get('name', '')}: manager task result unavailable")
                            completed += 1
                            await update_result(item)
                            await update_progress(completed, len(executable))
                    break
                await asyncio.sleep(1)
            else:
                raise UserFacingError("dependencies.manager_timeout")
        if git_actions:
            async def update_git_progress(done: int, total: int) -> None:
                await update_progress(completed + done, len(executable))

            await GitAdapter().execute(
                git_actions,
                on_log=add_log,
                on_progress=update_git_progress,
                on_result=update_result,
            )
        operation.result = {"tasks": list(results)}
        failed = next((item for item in results if item.get("state") == "failed"), None)
        if failed:
            operation.error_code = failed.get("error_code") or "dependencies.git_command_failed"
            operation.error_params = failed.get("error_params") or {}
            operation.status = "failed"
            operation.stage = "failed"
        else:
            operation.status = "success"
            operation.stage = "complete"
    except UserFacingError as exc:
        for item in results:
            if item.get("state") in {"queued", "installing"}:
                item["state"] = "failed"
                item["error_code"] = exc.code
                item["error_params"] = exc.params
        operation.result = {"tasks": list(results)}
        operation.status = "failed"
        operation.stage = "failed"
        operation.error_code = exc.code
        operation.error_params = exc.params
    except Exception as exc:
        operation.result = {"tasks": list(results)}
        operation.status = "failed"
        operation.stage = "failed"
        operation.logs.append(str(exc))


async def _run_dependency_operation(
    operation: Operation,
    actions: list[dict[str, Any]],
    manager_origin: str,
) -> None:
    async with _dependency_lock:
        await _perform_dependency_operation(operation, actions, manager_origin)


async def _refresh_startup_source(storage: UserStorage, owner: str, repo: str) -> list[dict[str, str]]:
    cache = storage.cache_dir / f"{owner}-{repo}.json"
    try:
        previous = Catalog.model_validate_json(cache.read_bytes()) if cache.exists() else None
        result = await refresh_subscription(storage, owner, repo)
        if not result["changed"] or previous is None:
            return []
        current = Catalog.model_validate_json(cache.read_bytes())
        return find_catalog_updates(previous, current, owner, repo)
    except Exception as exc:
        error_text = str(exc)

        def record_error(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
            for item in items:
                if (item["owner"], item["repo"]) == (owner, repo):
                    item["error"] = error_text
            return items

        await storage.update_json("subscriptions.json", [], record_error)
        return []


async def _refresh_startup_sources(storage: UserStorage) -> list[dict[str, str]]:
    updates: list[dict[str, str]] = []
    for source in await list_subscriptions(storage):
        updates.extend(await _refresh_startup_source(storage, source["owner"], source["repo"]))
    return updates


def _startup_refresh(storage: UserStorage) -> asyncio.Task[list[dict[str, str]]]:
    task = _startup_refresh_tasks.get(storage.key)
    if task is None:
        task = asyncio.create_task(_refresh_startup_sources(storage))
        _startup_refresh_tasks[storage.key] = task
    return task


def register_routes() -> None:
    global _registered
    if _registered:
        return
    try:
        from server import PromptServer
    except ImportError:
        return
    routes = PromptServer.instance.routes

    @routes.get("/workflow-hub")
    @endpoint
    async def page(_: web.Request) -> web.StreamResponse:
        path = FRONTEND / "index.html"
        if not path.exists():
            raise RuntimeError("前端构建产物缺失，请重新安装插件")
        response = web.FileResponse(path)
        response.headers["Cache-Control"] = "no-store"
        return response

    @routes.get("/workflow-hub/assets/{path:.*}")
    @endpoint
    async def assets(request: web.Request) -> web.StreamResponse:
        target = ensure_within(FRONTEND / "assets", FRONTEND / "assets" / request.match_info["path"])
        if not target.is_file():
            raise ValueError("资源不存在")
        response = web.FileResponse(target)
        response.headers["Cache-Control"] = "no-cache"
        return response

    @routes.get(f"{BASE}/status")
    @endpoint
    async def status(request: web.Request) -> web.StreamResponse:
        storage = UserStorage.from_request(request)
        _startup_refresh(storage)
        credential = await tokens.get_record(storage.key)
        github_user = credential.get("user") if credential and isinstance(credential.get("user"), dict) else None
        return web.json_response(
            {
                "plugin_version": "1.0.0",
                "minimum_frontend": "1.33.9",
                "comfyui_version": current_comfyui_version(),
                "git": local_git_status(),
                "manager": local_manager_status(),
                "github": {
                    "configured": bool(CLIENT_ID),
                    "authenticated": bool(credential and credential.get("access_token")),
                    "user": github_user,
                    "persistent_credentials": tokens.persistent,
                },
            }
        )

    @routes.post(f"{BASE}/update-notifications")
    @endpoint
    async def update_notifications(request: web.Request) -> web.StreamResponse:
        await _json(request)
        storage = UserStorage.from_request(request)
        updates = await _startup_refresh(storage)
        if storage.key in _startup_notifications_delivered:
            return web.json_response({"items": []})
        _startup_notifications_delivered.add(storage.key)
        return web.json_response({"items": updates})

    @routes.get(f"{BASE}/subscriptions")
    @endpoint
    async def subscriptions_get(request: web.Request) -> web.StreamResponse:
        return web.json_response({"items": await list_subscriptions(UserStorage.from_request(request))})

    @routes.post(f"{BASE}/subscriptions")
    @endpoint
    async def subscriptions_post(request: web.Request) -> web.StreamResponse:
        data = await _json(request)
        item = await add_subscription(UserStorage.from_request(request), str(data.get("url", "")))
        return web.json_response(item, status=201)

    @routes.delete(f"{BASE}/subscriptions/{{owner}}/{{repo}}")
    @endpoint
    async def subscriptions_delete(request: web.Request) -> web.StreamResponse:
        await _json(request)
        owner, repo = request.match_info["owner"], request.match_info["repo"]
        storage = UserStorage.from_request(request)
        await storage.update_json(
            "subscriptions.json",
            [],
            lambda items: [item for item in items if (item["owner"], item["repo"]) != (owner, repo)],
        )
        (storage.cache_dir / f"{owner}-{repo}.json").unlink(missing_ok=True)
        return web.json_response({"removed": True, "downloads_kept": True})

    @routes.post(f"{BASE}/subscriptions/{{owner}}/{{repo}}/refresh")
    @endpoint
    async def subscription_refresh(request: web.Request) -> web.StreamResponse:
        await _json(request)
        result = await refresh_subscription(
            UserStorage.from_request(request), request.match_info["owner"], request.match_info["repo"]
        )
        return web.json_response(result)

    @routes.get(f"{BASE}/workflows")
    @endpoint
    async def workflows(request: web.Request) -> web.StreamResponse:
        return web.json_response({"items": await aggregate_catalog(UserStorage.from_request(request))})

    @routes.post(f"{BASE}/workflows/download")
    @endpoint
    async def workflow_download(request: web.Request) -> web.StreamResponse:
        data = await _json(request)
        storage = UserStorage.from_request(request)
        cache = storage.cache_dir / f"{data['owner']}-{data['repo']}.json"
        catalog = Catalog.model_validate_json(cache.read_bytes())
        product = next(item for item in catalog.workflows if item.id == data["workflow_id"])
        version = next(item for item in product.versions if item.version == data["version"])
        operation = await operations.create("download")
        asyncio.create_task(_run(operation, download_version(storage, data["owner"], data["repo"], product, version, operation)))
        return web.json_response({"operation_id": operation.id}, status=202)

    @routes.post(f"{BASE}/workflows/models/download")
    @endpoint
    async def workflow_model_download(request: web.Request) -> web.StreamResponse:
        data = await _json(request)
        if data.get("confirmed") is not True:
            raise UserFacingError("lora.download_confirmation_required")
        storage = UserStorage.from_request(request)
        cache = storage.cache_dir / f"{data['owner']}-{data['repo']}.json"
        catalog = Catalog.model_validate_json(cache.read_bytes())
        product = next(item for item in catalog.workflows if item.id == data["workflow_id"])
        version = next(item for item in product.versions if item.version == data["version"])
        model = next(
            item
            for item in version.models
            if item.type == "loras" and item.filename == data["filename"]
        )
        operation = await operations.create("lora-download")
        asyncio.create_task(_run(operation, download_optional_lora(model, operation)))
        return web.json_response({"operation_id": operation.id}, status=202)

    @routes.delete(f"{BASE}/workflows/local")
    @endpoint
    async def workflow_local_delete(request: web.Request) -> web.StreamResponse:
        data = await _json(request)
        storage = UserStorage.from_request(request)
        installed = await storage.read_json("installed.json", [])
        key = (data["owner"], data["repo"], data["workflow_id"], data["version"])
        record = next(
            (
                item
                for item in installed
                if (item["owner"], item["repo"], item["workflow_id"], item["version"]) == key
            ),
            None,
        )
        if not record:
            raise ValueError("未找到已记录版本")
        target = ensure_within(storage.workflows_root, Path(record["path"]))
        target.unlink(missing_ok=True)
        await storage.write_json(
            "installed.json",
            [
                item
                for item in installed
                if (item["owner"], item["repo"], item["workflow_id"], item["version"]) != key
            ],
        )
        return web.json_response({"deleted": True})

    @routes.post(f"{BASE}/workflows/local/reveal")
    @endpoint
    async def workflow_local_reveal(request: web.Request) -> web.StreamResponse:
        data = await _json(request)
        storage = UserStorage.from_request(request)
        installed = await storage.read_json("installed.json", [])
        key = (data["owner"], data["repo"], data["workflow_id"], data["version"])
        record = next(
            (
                item
                for item in installed
                if (item["owner"], item["repo"], item["workflow_id"], item["version"]) == key
            ),
            None,
        )
        if not record:
            raise ValueError("未找到已记录版本")
        target = ensure_within(storage.workflows_root, Path(record["path"]))
        reveal_in_file_manager(target)
        return web.json_response({"opened": True})

    @routes.post(f"{BASE}/workflows/dependencies/plan")
    @endpoint
    async def dependency_plan(request: web.Request) -> web.StreamResponse:
        data = await _json(request)
        dependencies = data.get("dependencies", [])
        git_items = await GitAdapter().plan(dependencies)
        manager_items = await ManagerAdapter(f"{request.scheme}://{request.host}").plan(dependencies)
        planned = {
            (str(item.get("registry_id") or "") or str(item.get("source_url") or item.get("name"))): item
            for item in [*git_items, *manager_items]
        }
        result = [
            planned.get(
                str(item.get("registry_id") or "") or str(item.get("source_url") or item.get("name")),
                item,
            )
            for item in dependencies
        ]
        return web.json_response({"items": result})

    @routes.post(f"{BASE}/workflows/dependencies/execute")
    @endpoint
    async def dependency_execute(request: web.Request) -> web.StreamResponse:
        data = await _json(request)
        if data.get("confirmed") is not True:
            raise ValueError("必须明确确认后才能修改节点环境")
        operation = await operations.create("dependencies")
        manager_origin = f"{request.scheme}://{request.host}"
        asyncio.create_task(_run_dependency_operation(operation, data.get("actions", []), manager_origin))
        return web.json_response({"operation_id": operation.id}, status=202)

    @routes.get(f"{BASE}/github/repositories")
    @endpoint
    async def github_repositories(request: web.Request) -> web.StreamResponse:
        storage = UserStorage.from_request(request)
        token = await tokens.get(storage.key)
        if not token:
            raise ValueError("请先登录 GitHub")
        return web.json_response({"items": await _guarded_github_call(storage, GitHubClient(token).list_repositories())})

    @routes.get(f"{BASE}/publisher/catalog/{{owner}}/{{repo}}")
    @endpoint
    async def publisher_catalog(request: web.Request) -> web.StreamResponse:
        storage = UserStorage.from_request(request)
        token = await tokens.get(storage.key)
        if not token:
            raise ValueError("请先登录 GitHub")
        owner = request.match_info["owner"]
        repo = request.match_info["repo"]
        remote = await _guarded_github_call(storage, GitHubClient(token).get_catalog(owner, repo))
        if remote is None:
            return web.json_response({"categories": [], "workflows": []})
        catalog = Catalog.model_validate_json(remote.content)
        categories = sorted({item.category for item in catalog.workflows if item.category}, key=str.casefold)
        workflows = [
            {
                "id": item.id,
                "name": item.name,
                "category": item.category,
                "summary": item.summary,
                "description": item.description,
                "tags": item.tags,
                "versions": [version.version for version in item.versions],
            }
            for item in catalog.workflows
            if not item.archived
        ]
        return web.json_response({"categories": categories, "workflows": workflows})

    @routes.post(f"{BASE}/github/device/start")
    @endpoint
    async def github_device_start(request: web.Request) -> web.StreamResponse:
        await _json(request)
        data = await start_device_flow()
        storage = UserStorage.from_request(request)
        await storage.write_json(
            "device_flow.json",
            {"device_code": data["device_code"], "expires_in": data["expires_in"], "interval": data["interval"]},
        )
        return web.json_response(
            {
                "user_code": data["user_code"],
                "verification_uri": data["verification_uri"],
                "expires_in": data["expires_in"],
                "interval": data["interval"],
            }
        )

    @routes.post(f"{BASE}/github/device/poll")
    @endpoint
    async def github_device_poll(request: web.Request) -> web.StreamResponse:
        await _json(request)
        storage = UserStorage.from_request(request)
        flow = await storage.read_json("device_flow.json", None)
        if not flow:
            raise ValueError("登录请求不存在或已过期")
        data = await poll_device_flow(flow["device_code"])
        if "error" in data:
            return web.json_response({"pending": data["error"] in {"authorization_pending", "slow_down"}, "error": data["error"]})
        data["created_at"] = int(__import__("time").time())
        try:
            user, _ = await GitHubClient(str(data["access_token"])).request("GET", "https://api.github.com/user")
            data["user"] = {"login": user["login"], "avatar_url": user["avatar_url"]}
        except Exception:
            pass
        await tokens.set(storage.key, data)
        await storage.write_json("device_flow.json", {})
        return web.json_response({"authenticated": True, "credential_storage": "keyring" if tokens.persistent else "session"})

    @routes.post(f"{BASE}/github/refresh")
    @endpoint
    async def github_refresh(request: web.Request) -> web.StreamResponse:
        await _json(request)
        storage = UserStorage.from_request(request)
        credential = await tokens.get_record(storage.key)
        if not credential or not credential.get("refresh_token"):
            raise ValueError("当前 GitHub 凭据不可刷新，请重新登录")
        try:
            refreshed = await refresh_access_token(str(credential["refresh_token"]))
        except GitHubError as exc:
            if exc.status >= 500:
                raise
            # 刷新被拒（含 GitHub 以 200 返回 error 字段的情况）说明凭据已不可用。
            await tokens.delete(storage.key)
            raise GitHubError("GitHub 登录已失效，请重新登录", 401) from exc
        await tokens.set(storage.key, refreshed)
        return web.json_response({"authenticated": True})

    @routes.post(f"{BASE}/github/logout")
    @endpoint
    async def github_logout(request: web.Request) -> web.StreamResponse:
        await _json(request)
        await tokens.delete(UserStorage.from_request(request).key)
        return web.json_response({"authenticated": False})

    @routes.post(f"{BASE}/github/repositories")
    @endpoint
    async def github_repository_create(request: web.Request) -> web.StreamResponse:
        data = await _json(request)
        storage = UserStorage.from_request(request)
        token = await tokens.get(storage.key)
        if not token:
            raise ValueError("请先登录 GitHub")
        return web.json_response(
            await _guarded_github_call(
                storage,
                GitHubClient(token).create_repository(str(data.get("name", "")), str(data.get("description", ""))),
            ),
            status=201,
        )

    @routes.post(f"{BASE}/publisher/validate")
    @endpoint
    async def publisher_validate(request: web.Request) -> web.StreamResponse:
        data = await _json(request)
        product = WorkflowProduct.model_validate(prepare_publish_product(stamp_product_comfyui_version(data["product"])))
        if any(model.type == "loras" for version in product.versions for model in version.models):
            raise UserFacingError("publisher.lora_forbidden")
        if not isinstance(data.get("workflow"), dict):
            raise ValueError("工作流 JSON 必须是对象")
        images, _ = scan_workflow_assets(data["workflow"])
        failed_images = [item for item in images if item.status != "ready"]
        if failed_images:
            raise ValueError("工作流引用的加载图像存在缺失、超限或不支持的文件")
        return web.json_response({"valid": True})

    @routes.post(f"{BASE}/publisher/scan-dependencies")
    @endpoint
    async def publisher_scan_dependencies(request: web.Request) -> web.StreamResponse:
        await _json(request)
        items = await GitAdapter().installed_dependencies()
        return web.json_response({"items": items})

    @routes.post(f"{BASE}/publisher/scan-assets")
    @endpoint
    async def publisher_scan_assets(request: web.Request) -> web.StreamResponse:
        data = await _json(request)
        if not isinstance(data.get("workflow"), dict):
            raise ValueError("工作流 JSON 必须是对象")
        images, loras = scan_workflow_assets(data["workflow"])
        return web.json_response(
            {"images": [item.public() for item in images], "loras": [item.public() for item in loras]}
        )

    @routes.get(f"{BASE}/publisher/pending")
    @endpoint
    async def publisher_pending(request: web.Request) -> web.StreamResponse:
        return web.json_response({"items": await UserStorage.from_request(request).read_json("pending_publications.json", [])})

    @routes.post(f"{BASE}/publisher/pending/{{tag}}/resume")
    @endpoint
    async def publisher_pending_resume(request: web.Request) -> web.StreamResponse:
        await _json(request)
        storage = UserStorage.from_request(request)
        token = await tokens.get(storage.key)
        if not token:
            raise ValueError("请先登录 GitHub")
        pending = await storage.read_json("pending_publications.json", [])
        record = next((item for item in pending if item.get("tag") == request.match_info["tag"]), None)
        if not record:
            raise ValueError("待同步发布不存在")
        operation = await operations.create("publish-resume")
        asyncio.create_task(
            _run(
                operation,
                _guarded_github_call(
                    storage,
                    resume_publication(
                        storage,
                        token,
                        record,
                        operation,
                    ),
                ),
            )
        )
        return web.json_response({"operation_id": operation.id}, status=202)

    @routes.post(f"{BASE}/publisher/publish")
    @endpoint
    async def publisher_publish(request: web.Request) -> web.StreamResponse:
        data = await _json(request)
        product = stamp_product_comfyui_version(data["product"])
        storage = UserStorage.from_request(request)
        token = await tokens.get(storage.key)
        if not token:
            raise ValueError("请先登录 GitHub")
        owner, repo = parse_public_repository(str(data["repository_url"]))
        operation = await operations.create("publish")
        asyncio.create_task(
            _run(
                operation,
                _guarded_github_call(
                    storage,
                    publish(
                        storage,
                        token,
                        owner,
                        repo,
                        data["repository"],
                        product,
                        data["workflow"],
                        operation,
                        data.get("cover", data.get("preview")),
                        data.get("workflow_filename"),
                    ),
                ),
            )
        )
        return web.json_response({"operation_id": operation.id}, status=202)

    @routes.patch(f"{BASE}/publisher/workflows/{{owner}}/{{repo}}/{{workflow_id}}")
    @endpoint
    async def publisher_update(request: web.Request) -> web.StreamResponse:
        data = await _json(request)
        storage = UserStorage.from_request(request)
        token = await tokens.get(storage.key)
        if not token:
            raise ValueError("请先登录 GitHub")
        result = await _guarded_github_call(
            storage,
            update_product(
                token,
                request.match_info["owner"],
                request.match_info["repo"],
                request.match_info["workflow_id"],
                data,
            ),
        )
        return web.json_response(result)

    @routes.get(f"{BASE}/publisher/manage/{{owner}}/{{repo}}")
    @endpoint
    async def publisher_manage_list(request: web.Request) -> web.StreamResponse:
        storage = UserStorage.from_request(request)
        token = await tokens.get(storage.key)
        if not token:
            raise ValueError("请先登录 GitHub")
        items = await _guarded_github_call(
            storage,
            list_managed_products(token, request.match_info["owner"], request.match_info["repo"]),
        )
        return web.json_response({"items": items})

    @routes.delete(f"{BASE}/publisher/workflows/{{owner}}/{{repo}}/{{workflow_id}}")
    @endpoint
    async def publisher_workflow_delete(request: web.Request) -> web.StreamResponse:
        data = await _json(request)
        if data.get("confirmed") is not True:
            raise ValueError("必须明确确认后才能删除工作流")
        storage = UserStorage.from_request(request)
        token = await tokens.get(storage.key)
        if not token:
            raise ValueError("请先登录 GitHub")
        result = await _guarded_github_call(
            storage,
            delete_workflow(token, request.match_info["owner"], request.match_info["repo"], request.match_info["workflow_id"]),
        )
        return web.json_response(result)

    @routes.delete(f"{BASE}/publisher/workflows/{{owner}}/{{repo}}/{{workflow_id}}/versions/{{version}}")
    @endpoint
    async def publisher_version_delete(request: web.Request) -> web.StreamResponse:
        data = await _json(request)
        if data.get("confirmed") is not True:
            raise ValueError("必须明确确认后才能删除版本")
        storage = UserStorage.from_request(request)
        token = await tokens.get(storage.key)
        if not token:
            raise ValueError("请先登录 GitHub")
        result = await _guarded_github_call(
            storage,
            delete_version(
                token,
                request.match_info["owner"],
                request.match_info["repo"],
                request.match_info["workflow_id"],
                request.match_info["version"],
            ),
        )
        return web.json_response(result)

    @routes.patch(f"{BASE}/publisher/workflows/{{owner}}/{{repo}}/{{workflow_id}}/versions/{{version}}")
    @endpoint
    async def publisher_version_update(request: web.Request) -> web.StreamResponse:
        data = await _json(request)
        storage = UserStorage.from_request(request)
        token = await tokens.get(storage.key)
        if not token:
            raise ValueError("请先登录 GitHub")
        result = await _guarded_github_call(
            storage,
            update_version_changelog(
                token,
                request.match_info["owner"],
                request.match_info["repo"],
                request.match_info["workflow_id"],
                request.match_info["version"],
                str(data.get("changelog", "")),
            ),
        )
        return web.json_response(result)

    @routes.get(f"{BASE}/operations")
    @endpoint
    async def operations_list(_: web.Request) -> web.StreamResponse:
        return web.json_response({"items": await operations.list()})

    @routes.get(f"{BASE}/operations/{{operation_id}}")
    @endpoint
    async def operation_get(request: web.Request) -> web.StreamResponse:
        return web.json_response((await operations.get(request.match_info["operation_id"])).public())

    _registered = True
