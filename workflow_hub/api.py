from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path
from typing import Any, Awaitable, Callable, TypeVar
from urllib.parse import urlparse

import aiohttp
from aiohttp import web
from pydantic import ValidationError

from .assets import scan_workflow_assets
from .catalog import Catalog, WorkflowProduct, prepare_publish_product
from .compatibility import current_comfyui_version, stamp_product_comfyui_version
from .errors import UserFacingError
from .github import CLIENT_ID, GitHubClient, GitHubError, poll_device_flow, refresh_access_token, start_device_flow, tokens
from .legacy_manager import ManagerAdapter, local_manager_status
from .dependency_policy import is_ignored_dependency
from .manager import GitAdapter, local_git_status
from .operations import Operation, operations
from .security import ensure_within, parse_public_repository
from .service import (
    add_subscription,
    aggregate_catalog,
    clear_subscription_cache,
    delete_version,
    delete_workflow,
    download_version,
    find_catalog_updates,
    list_managed_products,
    list_subscriptions,
    publish,
    refresh_subscription,
    resume_publication,
    reveal_in_file_manager,
    subscription_cache_path,
    update_product,
    update_version_changelog,
)
from .storage import UserStorage

BASE = "/workflow-hub/api/v1"
ROOT = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "web" / "app"
MAX_JSON = 20 * 1024 * 1024
_registered = False
_startup_refresh_tasks: dict[str, asyncio.Task[dict[str, Any]]] = {}
_startup_notifications_delivered: set[str] = set()


async def _json(request: web.Request) -> dict[str, Any]:
    origin = request.headers.get("Origin")
    if origin:
        parsed = urlparse(origin)
        if parsed.netloc.casefold() != request.host.casefold() or parsed.scheme != request.scheme:
            raise UserFacingError("request.origin_invalid")
    if request.content_length and request.content_length > MAX_JSON:
        raise UserFacingError("request.body_too_large")
    raw = await request.read()
    if len(raw) > MAX_JSON:
        raise UserFacingError("request.body_too_large")
    if raw and request.content_type != "application/json":
        raise UserFacingError("request.content_type_invalid")
    try:
        data = json.loads(raw or b"{}")
    except json.JSONDecodeError as exc:
        raise UserFacingError("request.json_invalid") from exc
    if not isinstance(data, dict):
        raise UserFacingError("request.object_required")
    return data


def _source_parts(owner: Any, repo: Any) -> tuple[str, str]:
    try:
        return parse_public_repository(f"https://github.com/{str(owner).strip()}/{str(repo).strip()}")
    except ValueError as exc:
        raise UserFacingError("subscription.invalid_source") from exc


async def _require_subscribed_source(storage: UserStorage, owner: Any, repo: Any) -> tuple[str, str]:
    owner, repo = _source_parts(owner, repo)
    if not any(
        isinstance(item, dict)
        and str(item.get("owner", "")).casefold() == owner.casefold()
        and str(item.get("repo", "")).casefold() == repo.casefold()
        for item in await list_subscriptions(storage)
    ):
        raise UserFacingError("subscription.not_found")
    return owner, repo


def _publish_product_payload(data: dict[str, Any]) -> dict[str, Any]:
    product = data.get("product")
    if not isinstance(product, dict):
        raise UserFacingError("publisher.product_invalid")
    try:
        return stamp_product_comfyui_version(product)
    except (KeyError, TypeError, ValueError) as exc:
        raise UserFacingError("publisher.product_invalid") from exc


def _validate_publish_payload(data: dict[str, Any]) -> dict[str, Any]:
    product = _publish_product_payload(data)
    try:
        validated = WorkflowProduct.model_validate(prepare_publish_product(product))
    except (ValidationError, TypeError, ValueError) as exc:
        raise UserFacingError("publisher.product_invalid") from exc
    if len(validated.versions) != 1:
        raise UserFacingError("publisher.product_invalid")
    if any(model.type == "loras" for model in validated.versions[0].models):
        raise UserFacingError("publisher.lora_forbidden")
    if not isinstance(data.get("workflow"), dict):
        raise UserFacingError("publisher.workflow_invalid")
    if not isinstance(data.get("repository"), dict):
        raise UserFacingError("publisher.product_invalid")
    try:
        parse_public_repository(str(data.get("repository_url") or ""))
    except (TypeError, ValueError) as exc:
        raise UserFacingError("publisher.repository_invalid") from exc
    workflow_filename = data.get("workflow_filename")
    if workflow_filename is not None and not isinstance(workflow_filename, str):
        raise UserFacingError("publisher.product_invalid")
    cover = data.get("cover", data.get("preview"))
    if cover is not None and (
        not isinstance(cover, dict)
        or not isinstance(cover.get("filename"), str)
        or not isinstance(cover.get("data_base64"), str)
    ):
        raise UserFacingError("publisher.product_invalid")
    images, _ = scan_workflow_assets(data["workflow"])
    if any(item.status != "ready" for item in images):
        raise UserFacingError("publisher.assets_invalid")
    return product


def _catalog_version(catalog: Catalog, workflow_id: Any, version: Any) -> tuple[Any, Any]:
    product = next((item for item in catalog.workflows if item.id == str(workflow_id)), None)
    if product is None:
        raise UserFacingError("subscription.workflow_not_found")
    selected = next((item for item in product.versions if item.version == str(version)), None)
    if selected is None:
        raise UserFacingError("subscription.version_not_found")
    return product, selected


async def _github_token(storage: UserStorage) -> str:
    token = await tokens.get(storage.key)
    if not token:
        raise UserFacingError("github.authentication_required")
    return token


def _manager_origin(request: web.Request) -> str:
    transport = request.transport
    sockname = transport.get_extra_info("sockname") if transport else None
    if isinstance(sockname, tuple) and len(sockname) > 1 and isinstance(sockname[1], int):
        host = str(sockname[0])
        if host in {"0.0.0.0", "::"}:
            host = "127.0.0.1" if "." in host or host == "0.0.0.0" else "::1"
        if ":" in host and not host.startswith("["):
            host = f"[{host}]"
        return f"{request.scheme}://{host}:{sockname[1]}"
    return f"{request.scheme}://{request.host}"


def _dependency_key(item: dict[str, Any]) -> str:
    source = str(item.get("source_url") or "").strip().casefold().rstrip("/")
    if source:
        return f"git:{source.removesuffix('.git')}"
    registry_id = str(item.get("registry_id") or "").strip().casefold()
    if registry_id:
        return f"manager:{registry_id}"
    return f"name:{str(item.get('name') or '').strip().casefold()}"


def _normalise_dependency_plan(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    by_key: dict[str, dict[str, Any]] = {}
    for raw in items:
        item = dict(raw)
        if is_ignored_dependency(item):
            continue
        key = _dependency_key(item)
        item["task_id"] = key
        existing = by_key.get(key)
        if existing is None:
            by_key[key] = item
            result.append(item)
            continue
        requested = str(existing.get("requested") or "")
        duplicate_requested = str(item.get("requested") or "")
        if requested != duplicate_requested:
            existing["action"] = "conflict"
            existing["warning_code"] = (
                "dependencies.conflicting_commits"
                if key.startswith("git:")
                else "dependencies.conflicting_registry_versions"
            )
            existing["warning_params"] = {}
    return result


async def _plan_dependencies(
    dependencies: list[dict[str, Any]],
    version_policy: str,
    manager_origin: str,
) -> list[dict[str, Any]]:
    dependencies = [
        item for item in dependencies
        if not is_ignored_dependency(item)
    ]
    align_versions = version_policy == "align"
    git_items = await GitAdapter().plan(dependencies, align_versions=align_versions)
    manager_items = await ManagerAdapter(manager_origin).plan(dependencies, align_versions=align_versions)
    return _normalise_dependency_plan([*git_items, *manager_items])


def _dependency_from_action(item: dict[str, Any]) -> dict[str, Any]:
    dependency: dict[str, Any] = {
        "name": str(item.get("name") or ""),
        "registry_id": str(item.get("registry_id") or "").strip() or None,
        "source_url": str(item.get("source_url") or "").strip() or None,
        "required": item.get("required", True),
        "manual": item.get("manual", False),
    }
    requested = str(item.get("requested") or item.get("commit") or "").strip() or None
    if dependency["source_url"]:
        dependency["commit"] = requested
        dependency["registry_id"] = None
    else:
        dependency["version"] = requested
    return dependency


def _response_error(exc: Exception) -> web.Response:
    if isinstance(exc, UserFacingError):
        return web.json_response({"error_code": exc.code, "error_params": exc.params}, status=400)
    if isinstance(exc, ValidationError):
        return web.json_response(
            {
                "error_code": "request.invalid_payload",
                "error_params": {"detail": json.dumps(exc.errors(include_url=False), ensure_ascii=False)},
            },
            status=400,
        )
    if isinstance(exc, GitHubError):
        # 401 原样透传 HTTP 状态，前端据此把界面降级为未登录。
        status = 401 if exc.status == 401 else (502 if exc.status >= 500 or exc.status == 0 else 400)
        return web.json_response(
            {
                "error_code": "github.request_failed",
                "error_params": {"status": exc.status, "detail": str(exc)},
            },
            status=status,
        )
    if isinstance(exc, (ValueError, KeyError, json.JSONDecodeError)):
        return web.json_response(
            {"error_code": "request.invalid", "error_params": {"detail": str(exc).strip("'")}},
            status=400,
        )
    return web.json_response(
        {"error_code": "operation.failed", "error_params": {"detail": str(exc) or exc.__class__.__name__}},
        status=500,
    )


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
        result = await action
        if operation.status == "running":
            operation.stage = "complete"
            operation.status = "success"
            operation.result = result
    except UserFacingError as exc:
        operation.metadata["failed_stage"] = operation.stage
        operation.status = "failed"
        operation.stage = "failed"
        operation.error_code = exc.code
        operation.error_params = exc.params
    except Exception as exc:
        operation.metadata["failed_stage"] = operation.stage
        operation.status = "failed"
        operation.stage = "failed"
        operation.error_code = "operation.failed"
        operation.error_params = {"detail": str(exc)[-1000:]}
        operation.logs.append(str(exc))


def _publisher_management_action(changes: dict[str, Any]) -> str:
    if set(changes) == {"archived"} and changes.get("archived") is True:
        return "archive"
    if set(changes) == {"archived"} and changes.get("archived") is False:
        return "unarchive"
    return "edit_metadata"


async def _start_publisher_management_operation(
    request: web.Request,
    metadata: dict[str, Any],
    action: Callable[[str, Operation], Awaitable[dict[str, Any]]],
) -> web.Response:
    storage = UserStorage.from_request(request)
    token = await _github_token(storage)
    operation = await operations.create("publisher-manage", storage, metadata)

    async def run() -> dict[str, Any]:
        return await _guarded_github_call(storage, action(token, operation))

    asyncio.create_task(_run(operation, run()))
    return web.json_response({"operation_id": operation.id}, status=202)


_dependency_lock = asyncio.Lock()


async def _check_dependency_network(
    manager_actions: list[dict[str, Any]],
    git_actions: list[dict[str, Any]],
    on_log: Callable[[str], Awaitable[None]],
    manager_origin: str,
) -> None:
    hosts: list[str] = []
    for item in git_actions:
        source = str(item.get("source_url") or "").strip().rstrip("/")
        if source and source not in hosts:
            hosts.append(source)
    if manager_actions:
        hosts.extend((
            "https://api.comfy.org/",
            f"{manager_origin}/v2/manager/version",
            f"{manager_origin}/manager/version",
        ))
    if not hosts:
        return
    manager_version_hosts = {
        f"{manager_origin}/v2/manager/version",
        f"{manager_origin}/manager/version",
    } if manager_actions else set()
    github_hosts = {host for host in hosts if host.casefold().startswith("https://github.com/")}
    await on_log("network check: checking plugin download endpoints")
    timeout = aiohttp.ClientTimeout(total=10)

    async def check(session: aiohttp.ClientSession, host: str) -> tuple[str, str | None]:
        try:
            async with session.get(host, allow_redirects=False) as response:
                if (
                    response.status >= 500
                    or (host in manager_version_hosts and response.status >= 400)
                    or (host in github_hosts and response.status >= 400)
                ):
                    return host, f"HTTP {response.status}"
                return host, None
        except (aiohttp.ClientError, asyncio.TimeoutError, OSError) as exc:
            return host, str(exc) or exc.__class__.__name__

    semaphore = asyncio.Semaphore(8)

    async def bounded_check(session: aiohttp.ClientSession, host: str) -> tuple[str, str | None]:
        async with semaphore:
            return await check(session, host)

    async with aiohttp.ClientSession(timeout=timeout, trust_env=True) as session:
        results = await asyncio.gather(*(bounded_check(session, host) for host in hosts))
    failures = [(host, detail) for host, detail in results if detail and host not in manager_version_hosts]
    if manager_actions and not any(not detail for host, detail in results if host in manager_version_hosts):
        failures.extend((host, detail) for host, detail in results if host in manager_version_hosts and detail)
    for host, detail in results:
        await on_log(f"network check: {host} -> {'ok' if not detail else detail}")
    if failures:
        host, detail = failures[0]
        raise UserFacingError("dependencies.network_unavailable", {"host": host, "detail": detail or "unknown error"})
    await on_log("network check: download endpoints are reachable")


async def _perform_dependency_operation(
    operation: Operation,
    actions: list[dict[str, Any]],
    manager_origin: str,
) -> None:
    executable = [item for item in actions if item.get("action") in {"install", "upgrade", "downgrade"}]
    manager_actions = [item for item in executable if item.get("registry_id") and not item.get("source_url")]
    git_actions = [item for item in executable if item not in manager_actions]
    operation.progress_mode = "tasks"
    progress_total = len(manager_actions) + len(git_actions) * 2
    network_steps = 1 if executable else 0
    operation.progress = {"received": 0, "total": progress_total + network_steps}
    results: list[dict[str, Any]] = [
        {
            "task_id": item.get("task_id"),
            "name": item.get("name", item.get("registry_id") or item.get("source_url") or ""),
            "requested": item.get("requested"),
            "action": item.get("action", ""),
            "state": "success" if item.get("action") == "keep" else "queued",
            "registry_id": item.get("registry_id"),
            "source_url": item.get("source_url"),
            "installer": item.get("installer"),
        }
        for item in actions
        if item.get("action") in {"keep", "install", "upgrade", "downgrade"}
    ]

    async def add_log(line: str) -> None:
        text = line.replace("\r", "").strip()
        if text:
            operation.logs.append(text)

    async def update_progress(done: int, total: int) -> None:
        operation.progress = {"received": done, "total": total}

    async def update_result(result: dict[str, Any]) -> None:
        key = str(result.get("task_id") or result.get("registry_id") or result.get("source_url") or result.get("name") or "")
        existing = next(
            (item for item in results if str(item.get("task_id") or item.get("registry_id") or item.get("source_url") or item.get("name") or "") == key),
            None,
        )
        if existing is None:
            results.append(result)
        else:
            existing.update(result)
        operation.result = {"tasks": list(results)}
        if result.get("state") == "failed":
            code = result.get("error_code") or "dependencies.git_command_failed"
            params = result.get("error_params") or {}
            await add_log(f"{result.get('name', '')}: {code} {params}")

    try:
        operation.stage = "checking_network"
        completed = 0
        if network_steps:
            await _check_dependency_network(manager_actions, git_actions, add_log, manager_origin)
            completed = network_steps
            await update_progress(completed, progress_total + network_steps)
        operation.stage = "installing"
        manager_completed = 0
        if manager_actions:
            manager = ManagerAdapter(manager_origin)
            baseline_status = await manager.queue_status(operation.id)
            await add_log("manager queue: submitting dependency tasks")
            async def manager_task_queued(item: dict[str, Any]) -> None:
                await update_result({
                    "task_id": item.get("task_id"),
                    "name": item.get("name", item.get("registry_id", "")),
                    "requested": item.get("requested"),
                    "action": item.get("action", "install"),
                    "state": "queued",
                    "registry_id": item.get("registry_id"),
                    "installer": "manager",
                })

            queued = await manager.execute(manager_actions, operation.id, on_queued=manager_task_queued)
            for item in queued:
                await update_result({
                    "task_id": item.get("task_id"),
                    "name": item.get("name", item.get("registry_id", "")),
                    "requested": item.get("requested"),
                    "action": item.get("action", "install"),
                    "state": "installing",
                    "registry_id": item.get("registry_id"),
                    "installer": "manager",
                })
            await update_progress(completed, progress_total + network_steps)
            history_seen: set[str] = set()
            last_status: tuple[int, int, int, bool] | None = None
            manager_idle_polls = 0
            for _ in range(1800):
                status = await manager.queue_status(operation.id)
                manager_idle_polls = 0 if status["processing"] else manager_idle_polls + 1
                snapshot = (status["total"], status["done"], status["in_progress"], status["processing"])
                if snapshot != last_status:
                    await add_log(f"manager queue: total={snapshot[0]} done={snapshot[1]} in_progress={snapshot[2]} processing={snapshot[3]}")
                    last_status = snapshot
                history = await manager.queue_history(operation.id)
                legacy = status.get("api") == "legacy"
                done_count = max(0, status["done"] - baseline_status["done"]) if legacy else status["done"]
                total_count = max(0, status["total"] - baseline_status["total"]) if legacy else status["total"]
                await update_progress(network_steps + max(manager_completed, min(done_count, len(manager_actions)), 0), progress_total + network_steps)
                for item in results:
                    if item.get("installer") != "manager" or item.get("action") not in {"install", "upgrade", "downgrade"}:
                        continue
                    key = str(item.get("registry_id") or "")
                    outcome = history.get(key)
                    if not outcome or key in history_seen:
                        continue
                    history_seen.add(key)
                    item["state"] = outcome["outcome"]
                    item["message"] = outcome.get("message", "")
                    if item["message"]:
                        await add_log(f"{item.get('name', '')}: {item['message']}")
                    if item["state"] == "failed":
                        item["error_code"] = "dependencies.manager_task_failed"
                        item["error_params"] = {"name": item["name"]}
                    manager_completed += 1
                    await update_result(item)
                    await update_progress(network_steps + manager_completed, progress_total + network_steps)
                if manager_completed >= len(manager_actions):
                    break
                if not status["processing"] and manager_idle_polls >= 3 and (total_count == 0 or done_count >= len(manager_actions)):
                    if legacy:
                        for item in results:
                            if item.get("installer") != "manager" or item.get("state") != "installing":
                                continue
                            item["state"] = "unknown"
                            item["error_code"] = "dependencies.manager_result_unknown"
                            item["error_params"] = {"name": item.get("name", "")}
                            item["message"] = "manager task result unavailable"
                            await add_log(f"{item.get('name', '')}: {item['message']}")
                            await update_result(item)
                        manager_completed = len(manager_actions)
                        await update_progress(network_steps + manager_completed, progress_total + network_steps)
                        break
                    try:
                        verified = await manager.verify_actions(manager_actions)
                    except UserFacingError:
                        verified = {}
                    for item in results:
                        if item.get("state") != "installing":
                            continue
                        outcome = verified.get(str(item.get("registry_id") or ""))
                        if outcome and outcome.get("state") == "success":
                            item["state"] = "success"
                            item["message"] = outcome.get("message", "")
                        elif outcome:
                            item["state"] = "failed"
                            item["error_code"] = "dependencies.manager_task_failed"
                            item["error_params"] = {"name": item.get("name", "")}
                            item["message"] = outcome.get("message", "")
                        else:
                            item["state"] = "unknown"
                            item["error_code"] = "dependencies.manager_result_unknown"
                            item["error_params"] = {"name": item.get("name", "")}
                            item["message"] = "manager task result unavailable"
                        if item.get("message"):
                            await add_log(f"{item.get('name', '')}: {item['message']}")
                        manager_completed += 1
                        await update_result(item)
                        await update_progress(network_steps + manager_completed, progress_total + network_steps)
                    break
                await asyncio.sleep(1)
            else:
                raise UserFacingError("dependencies.manager_timeout")
        if git_actions:
            async def update_git_progress(done: int, total: int) -> None:
                await update_progress(network_steps + manager_completed + done, progress_total + network_steps)

            await GitAdapter().execute(
                git_actions,
                on_log=add_log,
                on_progress=update_git_progress,
                on_result=update_result,
            )
        operation.result = {"tasks": list(results)}
        failed = next((item for item in results if item.get("state") in {"failed", "unknown"}), None)
        if failed:
            if failed.get("state") == "unknown":
                failed["error_code"] = "dependencies.manager_result_unknown"
                failed["error_params"] = {"name": failed.get("name", "")}
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
    except (aiohttp.ClientError, asyncio.TimeoutError, OSError, ValueError) as exc:
        code = "dependencies.manager_request_failed" if manager_actions else "dependencies.operation_failed"
        params = {"status": 0, "detail": str(exc)[-1000:]} if manager_actions else {"detail": str(exc)[-1000:]}
        for item in results:
            if item.get("state") in {"queued", "installing", "python_installing"}:
                item["state"] = "failed"
                item["error_code"] = code
                item["error_params"] = {"name": item.get("name", ""), **params}
        operation.result = {"tasks": list(results)}
        operation.status = "failed"
        operation.stage = "failed"
        operation.error_code = code
        operation.error_params = params
        operation.logs.append(str(exc))
    except Exception as exc:
        for item in results:
            if item.get("state") in {"queued", "installing", "python_installing"}:
                item["state"] = "failed"
                item["error_code"] = "dependencies.manager_task_failed"
                item["error_params"] = {"name": item.get("name", ""), "detail": str(exc)[-1000:]}
        operation.result = {"tasks": list(results)}
        operation.status = "failed"
        operation.stage = "failed"
        operation.error_code = "dependencies.operation_failed"
        operation.error_params = {"detail": str(exc)[-1000:]}
        operation.logs.append(str(exc))


async def _run_dependency_operation(
    operation: Operation,
    actions: list[dict[str, Any]],
    manager_origin: str,
) -> None:
    async with _dependency_lock:
        await _perform_dependency_operation(operation, actions, manager_origin)


async def _refresh_startup_source(storage: UserStorage, owner: str, repo: str) -> tuple[list[dict[str, str]], bool]:
    cache = subscription_cache_path(storage, owner, repo)
    previous_error = None
    try:
        previous_source = next(
            (
                item for item in await list_subscriptions(storage)
                if isinstance(item, dict)
                and str(item.get("owner", "")).casefold() == owner.casefold()
                and str(item.get("repo", "")).casefold() == repo.casefold()
            ),
            None,
        )
        previous_error = previous_source.get("error") if previous_source else None
        previous = None
        if cache.exists():
            try:
                previous = Catalog.model_validate_json(cache.read_bytes())
            except (OSError, ValidationError, ValueError):
                clear_subscription_cache(storage, owner, repo)
        result = await refresh_subscription(storage, owner, repo)
        catalog_changed = bool(
            result["changed"]
            or result["catalog_missing"]
            or previous_error
        )
        if not catalog_changed:
            return [], False
        if not result["changed"] or previous is None:
            return [], True
        current = Catalog.model_validate_json(subscription_cache_path(storage, owner, repo).read_bytes())
        return find_catalog_updates(previous, current, owner, repo), True
    except Exception:
        def record_error(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
            for item in items:
                if isinstance(item, dict) and str(item.get("owner", "")).casefold() == owner.casefold() and str(item.get("repo", "")).casefold() == repo.casefold():
                    item["error"] = "subscription.refresh_failed"
            return items

        await storage.update_json("subscriptions.json", [], record_error)
        return [], True


async def _refresh_startup_sources(storage: UserStorage) -> dict[str, Any]:
    updates: list[dict[str, str]] = []
    catalog_changed = False
    for source in await list_subscriptions(storage):
        if not isinstance(source, dict) or not source.get("owner") or not source.get("repo"):
            continue
        source_updates, source_changed = await _refresh_startup_source(storage, str(source["owner"]), str(source["repo"]))
        updates.extend(source_updates)
        catalog_changed = catalog_changed or source_changed
    return {"items": updates, "catalog_changed": catalog_changed}


def _startup_refresh(storage: UserStorage) -> asyncio.Task[dict[str, Any]]:
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
                "plugin_version": "1.0.1",
                "catalog_cache_scope": hashlib.sha256(storage.key.encode("utf-8")).hexdigest()[:32],
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
        result = await _startup_refresh(storage)
        if storage.key in _startup_notifications_delivered:
            return web.json_response({"items": [], "catalog_changed": False})
        _startup_notifications_delivered.add(storage.key)
        return web.json_response(result)

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
        owner, repo = _source_parts(request.match_info["owner"], request.match_info["repo"])
        storage = UserStorage.from_request(request)
        await storage.update_json(
            "subscriptions.json",
            [],
            lambda items: [
                item for item in items
                if not (item.get("owner", "").casefold() == owner.casefold() and item.get("repo", "").casefold() == repo.casefold())
            ],
        )
        clear_subscription_cache(storage, owner, repo)
        return web.json_response({"removed": True, "downloads_kept": True})

    @routes.post(f"{BASE}/subscriptions/{{owner}}/{{repo}}/refresh")
    @endpoint
    async def subscription_refresh(request: web.Request) -> web.StreamResponse:
        await _json(request)
        owner, repo = _source_parts(request.match_info["owner"], request.match_info["repo"])
        result = await refresh_subscription(UserStorage.from_request(request), owner, repo)
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
        owner, repo = await _require_subscribed_source(storage, data.get("owner"), data.get("repo"))
        data["owner"], data["repo"] = owner, repo
        cache = subscription_cache_path(storage, owner, repo)
        if not cache.is_file():
            raise UserFacingError("subscription.catalog_missing")
        catalog = Catalog.model_validate_json(cache.read_bytes())
        product, version = _catalog_version(catalog, data.get("workflow_id"), data.get("version"))
        operation = await operations.create(
            "download",
            storage,
            {"owner": data["owner"], "repo": data["repo"], "workflow_id": data["workflow_id"], "version": data["version"]},
        )
        asyncio.create_task(_run(operation, download_version(storage, data["owner"], data["repo"], product, version, operation)))
        return web.json_response({"operation_id": operation.id}, status=202)

    @routes.delete(f"{BASE}/workflows/local")
    @endpoint
    async def workflow_local_delete(request: web.Request) -> web.StreamResponse:
        data = await _json(request)
        storage = UserStorage.from_request(request)
        owner, repo = _source_parts(data.get("owner"), data.get("repo"))
        key = (owner.casefold(), repo.casefold(), str(data.get("workflow_id") or ""), str(data.get("version") or ""))
        installed = await storage.read_json("installed.json", [])
        record = next(
            (
                item
                for item in installed
                if (
                    str(item.get("owner", "")).casefold(),
                    str(item.get("repo", "")).casefold(),
                    str(item.get("workflow_id", "")),
                    str(item.get("version", "")),
                ) == key
            ),
            None,
        )
        if not record:
            raise UserFacingError("subscription.local_version_not_found")
        target = ensure_within(storage.workflows_root, Path(record["path"]))
        target.unlink(missing_ok=True)

        def remove_record(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
            return [
                item
                for item in items
                if (
                    str(item.get("owner", "")).casefold(),
                    str(item.get("repo", "")).casefold(),
                    str(item.get("workflow_id", "")),
                    str(item.get("version", "")),
                ) != key
            ]

        await storage.update_json("installed.json", [], remove_record)
        return web.json_response({"deleted": True})

    @routes.post(f"{BASE}/workflows/local/reveal")
    @endpoint
    async def workflow_local_reveal(request: web.Request) -> web.StreamResponse:
        data = await _json(request)
        storage = UserStorage.from_request(request)
        installed = await storage.read_json("installed.json", [])
        owner, repo = _source_parts(data.get("owner"), data.get("repo"))
        key = (owner.casefold(), repo.casefold(), str(data.get("workflow_id") or ""), str(data.get("version") or ""))
        record = next(
            (
                item for item in installed
                if (
                    str(item.get("owner", "")).casefold(),
                    str(item.get("repo", "")).casefold(),
                    str(item.get("workflow_id", "")),
                    str(item.get("version", "")),
                ) == key
            ),
            None,
        )
        if not record:
            raise UserFacingError("subscription.local_version_not_found")
        target = ensure_within(storage.workflows_root, Path(record["path"]))
        reveal_in_file_manager(target)
        return web.json_response({"opened": True})

    @routes.post(f"{BASE}/workflows/local/load")
    @endpoint
    async def workflow_local_load(request: web.Request) -> web.StreamResponse:
        data = await _json(request)
        storage = UserStorage.from_request(request)
        installed = await storage.read_json("installed.json", [])
        owner, repo = _source_parts(data.get("owner"), data.get("repo"))
        key = (owner.casefold(), repo.casefold(), str(data.get("workflow_id") or ""), str(data.get("version") or ""))
        record = next(
            (
                item for item in installed
                if (
                    str(item.get("owner", "")).casefold(),
                    str(item.get("repo", "")).casefold(),
                    str(item.get("workflow_id", "")),
                    str(item.get("version", "")),
                ) == key
            ),
            None,
        )
        if not record:
            raise UserFacingError("subscription.local_version_not_found")
        target = ensure_within(storage.workflows_root, Path(record["path"]))
        if not target.is_file():
            raise UserFacingError("subscription.local_file_missing")
        return web.json_response({"workflow": json.loads(target.read_text(encoding="utf-8"))})

    @routes.post(f"{BASE}/workflows/dependencies/plan")
    @endpoint
    async def dependency_plan(request: web.Request) -> web.StreamResponse:
        data = await _json(request)
        dependencies = data.get("dependencies", [])
        version_policy = str(data.get("version_policy") or "align").strip().casefold()
        if version_policy not in {"align", "warn"}:
            raise UserFacingError("dependencies.invalid_version_policy")
        if not isinstance(dependencies, list) or not all(isinstance(item, dict) for item in dependencies):
            raise UserFacingError("dependencies.invalid_plan")
        result = await _plan_dependencies(dependencies, version_policy, _manager_origin(request))
        return web.json_response({"items": result})

    @routes.post(f"{BASE}/workflows/dependencies/execute")
    @endpoint
    async def dependency_execute(request: web.Request) -> web.StreamResponse:
        data = await _json(request)
        if data.get("confirmed") is not True:
            raise UserFacingError("dependencies.confirmation_required")
        version_policy = str(data.get("version_policy") or "align").strip().casefold()
        if version_policy not in {"align", "warn"}:
            raise UserFacingError("dependencies.invalid_version_policy")
        selected = data.get("actions", [])
        if not selected or not isinstance(selected, list) or not all(isinstance(item, dict) for item in selected):
            raise UserFacingError("dependencies.invalid_plan")
        manager_origin = _manager_origin(request)
        fresh_plan = await _plan_dependencies(
            [_dependency_from_action(item) for item in selected],
            version_policy,
            manager_origin,
        )
        selected_keys = {_dependency_key(item) for item in selected}
        fresh_by_key = {str(item.get("task_id")): item for item in fresh_plan}
        actions: list[dict[str, Any]] = []
        for selected_item in selected:
            key = _dependency_key(selected_item)
            fresh = fresh_by_key.get(key)
            if fresh is None or fresh.get("action") in {"manual", "unknown", "conflict"}:
                raise UserFacingError(
                    "dependencies.plan_changed",
                    {"name": str(selected_item.get("name") or selected_item.get("registry_id") or selected_item.get("source_url") or key)},
                )
            if key in selected_keys:
                actions.append(fresh)
        metadata = dict(data.get("metadata") or {})
        metadata["actions"] = [
            {
                "task_id": item.get("task_id"),
                "name": item.get("name"),
                "registry_id": item.get("registry_id"),
                "source_url": item.get("source_url"),
                "requested": item.get("requested"),
                "action": item.get("action"),
                "installer": item.get("installer"),
            }
            for item in actions
        ]
        storage = UserStorage.from_request(request)
        operation = await operations.create("dependencies", storage, metadata)
        asyncio.create_task(_run_dependency_operation(operation, actions, manager_origin))
        return web.json_response({"operation_id": operation.id}, status=202)

    @routes.get(f"{BASE}/github/repositories")
    @endpoint
    async def github_repositories(request: web.Request) -> web.StreamResponse:
        storage = UserStorage.from_request(request)
        token = await _github_token(storage)
        return web.json_response({"items": await _guarded_github_call(storage, GitHubClient(token).list_repositories())})

    @routes.get(f"{BASE}/publisher/catalog/{{owner}}/{{repo}}")
    @endpoint
    async def publisher_catalog(request: web.Request) -> web.StreamResponse:
        storage = UserStorage.from_request(request)
        token = await _github_token(storage)
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
            raise UserFacingError("github.login_expired")
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
            raise UserFacingError("github.credential_unavailable")
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
        token = await _github_token(storage)
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
        _validate_publish_payload(data)
        return web.json_response({"valid": True})

    @routes.post(f"{BASE}/publisher/scan-dependencies")
    @endpoint
    async def publisher_scan_dependencies(request: web.Request) -> web.StreamResponse:
        await _json(request)
        try:
            items = [
                item for item in await GitAdapter().installed_dependencies()
                if not is_ignored_dependency(item)
            ]
        except UserFacingError:
            items = []
        return web.json_response({"items": items})

    @routes.post(f"{BASE}/publisher/scan-assets")
    @endpoint
    async def publisher_scan_assets(request: web.Request) -> web.StreamResponse:
        data = await _json(request)
        if not isinstance(data.get("workflow"), dict):
            raise UserFacingError("publisher.workflow_invalid")
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
        token = await _github_token(storage)
        pending = await storage.read_json("pending_publications.json", [])
        record = next((item for item in pending if item.get("tag") == request.match_info["tag"]), None)
        if not record:
            raise UserFacingError("publisher.pending_not_found")
        operation = await operations.create("publish-resume", storage, {"tag": record.get("tag", "")})
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
        product = _validate_publish_payload(data)
        try:
            owner, repo = parse_public_repository(str(data.get("repository_url") or ""))
        except (TypeError, ValueError) as exc:
            raise UserFacingError("publisher.repository_invalid") from exc
        storage = UserStorage.from_request(request)
        token = await _github_token(storage)
        operation = await operations.create("publish", storage, {"owner": owner, "repo": repo, "workflow_id": product.get("id", "")})
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
        owner = request.match_info["owner"]
        repo = request.match_info["repo"]
        workflow_id = request.match_info["workflow_id"]
        action_name = _publisher_management_action(data)
        return await _start_publisher_management_operation(
            request,
            {
                "action": action_name,
                "owner": owner,
                "repo": repo,
                "workflow_id": workflow_id,
            },
            lambda token, operation: update_product(
                token,
                owner,
                repo,
                workflow_id,
                data,
                operation=operation,
            ),
        )

    @routes.get(f"{BASE}/publisher/manage/{{owner}}/{{repo}}")
    @endpoint
    async def publisher_manage_list(request: web.Request) -> web.StreamResponse:
        storage = UserStorage.from_request(request)
        token = await _github_token(storage)
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
            raise UserFacingError("publisher.confirmation_required")
        owner = request.match_info["owner"]
        repo = request.match_info["repo"]
        workflow_id = request.match_info["workflow_id"]
        return await _start_publisher_management_operation(
            request,
            {
                "action": "delete_workflow",
                "owner": owner,
                "repo": repo,
                "workflow_id": workflow_id,
            },
            lambda token, operation: delete_workflow(
                token,
                owner,
                repo,
                workflow_id,
                operation=operation,
            ),
        )

    @routes.delete(f"{BASE}/publisher/workflows/{{owner}}/{{repo}}/{{workflow_id}}/versions/{{version}}")
    @endpoint
    async def publisher_version_delete(request: web.Request) -> web.StreamResponse:
        data = await _json(request)
        if data.get("confirmed") is not True:
            raise UserFacingError("publisher.confirmation_required")
        owner = request.match_info["owner"]
        repo = request.match_info["repo"]
        workflow_id = request.match_info["workflow_id"]
        version = request.match_info["version"]
        return await _start_publisher_management_operation(
            request,
            {
                "action": "delete_version",
                "owner": owner,
                "repo": repo,
                "workflow_id": workflow_id,
                "version": version,
            },
            lambda token, operation: delete_version(
                token,
                owner,
                repo,
                workflow_id,
                version,
                operation=operation,
            ),
        )

    @routes.patch(f"{BASE}/publisher/workflows/{{owner}}/{{repo}}/{{workflow_id}}/versions/{{version}}")
    @endpoint
    async def publisher_version_update(request: web.Request) -> web.StreamResponse:
        data = await _json(request)
        owner = request.match_info["owner"]
        repo = request.match_info["repo"]
        workflow_id = request.match_info["workflow_id"]
        version = request.match_info["version"]
        return await _start_publisher_management_operation(
            request,
            {
                "action": "edit_changelog",
                "owner": owner,
                "repo": repo,
                "workflow_id": workflow_id,
                "version": version,
            },
            lambda token, operation: update_version_changelog(
                token,
                owner,
                repo,
                workflow_id,
                version,
                str(data.get("changelog", "")),
                operation=operation,
            ),
        )

    @routes.post(f"{BASE}/operations/{{operation_id}}/manager-results")
    @endpoint
    async def operation_manager_results(request: web.Request) -> web.StreamResponse:
        data = await _json(request)
        storage = UserStorage.from_request(request)
        operation = await operations.get(request.match_info["operation_id"], storage)
        if operation.kind != "dependencies":
            raise UserFacingError("operation.invalid_manager_result")
        late_manager_result = operation.status == "failed" and operation.error_code == "dependencies.manager_result_unknown"
        if operation.status != "running" and not late_manager_result:
            return web.json_response(operation.public())
        results = data.get("results") if isinstance(data.get("results"), dict) else {}
        tasks = operation.result.get("tasks", []) if isinstance(operation.result, dict) else []
        failed = False
        for task in tasks:
            registry_id = str(task.get("registry_id") or "")
            update = results.get(registry_id)
            if not registry_id or not isinstance(update, dict):
                continue
            state = str(update.get("state") or "").casefold()
            if state not in {"success", "failed"}:
                continue
            task["state"] = state
            task["message"] = str(update.get("message") or "")
            task["error_code"] = None if state == "success" else "dependencies.manager_task_failed"
            task["error_params"] = {} if state == "success" else {"name": task.get("name", ""), "detail": task.get("message", "")}
            if state == "failed":
                failed = True
            if task["message"]:
                operation.logs.append(f"{task.get('name', registry_id)}: {task['message']}")
        if isinstance(operation.result, dict):
            operation.result["tasks"] = tasks
        if failed:
            operation.status = "failed"
            operation.stage = "failed"
            operation.error_code = "dependencies.manager_task_failed"
            operation.error_params = {}
        elif operation.status == "failed" and tasks and all(
            task.get("state") in {"success", "keep"} for task in tasks
        ):
            operation.status = "success"
            operation.stage = "complete"
            operation.error_code = None
            operation.error_params = None
        await operations.persist(operation)
        return web.json_response(operation.public())

    @routes.delete(f"{BASE}/operations/completed")
    @endpoint
    async def operations_delete_completed(request: web.Request) -> web.StreamResponse:
        await _json(request)
        deleted = await operations.delete_completed(UserStorage.from_request(request))
        return web.json_response({"deleted": len(deleted), "ids": deleted})

    @routes.delete(f"{BASE}/operations/{{operation_id}}")
    @endpoint
    async def operation_delete(request: web.Request) -> web.StreamResponse:
        await _json(request)
        storage = UserStorage.from_request(request)
        result = await operations.delete(request.match_info["operation_id"], storage)
        if result == "not_found":
            raise UserFacingError("operation.not_found")
        if result == "active":
            raise UserFacingError("operation.active")
        return web.json_response({"deleted": True, "operation_id": request.match_info["operation_id"]})

    @routes.get(f"{BASE}/operations")
    @endpoint
    async def operations_list(request: web.Request) -> web.StreamResponse:
        return web.json_response({"items": await operations.list(UserStorage.from_request(request))})

    @routes.get(f"{BASE}/operations/{{operation_id}}")
    @endpoint
    async def operation_get(request: web.Request) -> web.StreamResponse:
        storage = UserStorage.from_request(request)
        return web.json_response((await operations.get(request.match_info["operation_id"], storage)).public())

    _registered = True
