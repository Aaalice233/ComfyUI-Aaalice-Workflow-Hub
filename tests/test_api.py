import json
import unittest
from unittest.mock import AsyncMock, patch

from aiohttp import web

from workflow_hub import api as api_module
from workflow_hub.api import _guarded_github_call, _json, _response_error, _run, endpoint
from workflow_hub.errors import UserFacingError
from workflow_hub.github import GitHubError, tokens
from workflow_hub.operations import Operation


class RequestStub:
    def __init__(self, body: bytes, content_type: str = "application/octet-stream") -> None:
        self._body = body
        self.headers: dict[str, str] = {}
        self.host = "127.0.0.1:8188"
        self.scheme = "http"
        self.content_type = content_type
        self.content_length = len(body)

    async def read(self) -> bytes:
        return self._body


class EndpointHeaderTests(unittest.IsolatedAsyncioTestCase):
    async def test_api_responses_are_not_cached(self) -> None:
        async def handler(_request):
            return web.json_response({"ok": True})

        response = await endpoint(handler)(object())
        self.assertEqual(response.headers["Cache-Control"], "no-store")


class JsonRequestTests(unittest.IsolatedAsyncioTestCase):
    async def test_empty_write_body_does_not_require_content_type(self) -> None:
        self.assertEqual(await _json(RequestStub(b"")), {})

    async def test_non_empty_body_requires_json_content_type(self) -> None:
        with self.assertRaises(UserFacingError) as caught:
            await _json(RequestStub(b"{}", "text/plain"))
        self.assertEqual(caught.exception.code, "request.content_type_invalid")

    async def test_invalid_json_uses_a_stable_error_code(self) -> None:
        with self.assertRaises(UserFacingError) as caught:
            await _json(RequestStub(b"{", "application/json"))
        self.assertEqual(caught.exception.code, "request.json_invalid")

    async def test_json_object_is_parsed(self) -> None:
        self.assertEqual(await _json(RequestStub(b'{"value": 1}', "application/json")), {"value": 1})


class StorageStub:
    key = "test-guarded-call-user"


class GuardedGitHubCallTests(unittest.IsolatedAsyncioTestCase):
    async def asyncTearDown(self) -> None:
        tokens._session_tokens.clear()
        tokens._deleted.clear()

    async def test_401_clears_stored_credential(self) -> None:
        tokens._session_tokens[StorageStub.key] = '{"access_token": "dead"}'

        async def fail():
            raise GitHubError("Bad credentials", 401)

        with self.assertRaisesRegex(GitHubError, "重新登录") as caught:
            await _guarded_github_call(StorageStub(), "dead", fail())
        self.assertEqual(caught.exception.status, 401)
        self.assertIsNone(await tokens.get(StorageStub.key))

    async def test_stale_401_does_not_clear_rotated_credential(self) -> None:
        tokens._session_tokens[StorageStub.key] = '{"access_token": "new"}'

        async def fail():
            raise GitHubError("Bad credentials", 401)

        with self.assertRaises(UserFacingError) as caught:
            await _guarded_github_call(StorageStub(), "old", fail())
        self.assertEqual(caught.exception.code, "github.credential_rotated")
        self.assertEqual(await tokens.get(StorageStub.key), "new")

    async def test_other_errors_keep_credential(self) -> None:
        tokens._session_tokens[StorageStub.key] = '{"access_token": "live"}'

        async def fail():
            raise GitHubError("boom", 500)

        with self.assertRaises(GitHubError):
            await _guarded_github_call(StorageStub(), "live", fail())
        self.assertEqual(await tokens.get(StorageStub.key), "live")

    async def test_result_passes_through(self) -> None:
        async def ok():
            return {"items": []}

        self.assertEqual(await _guarded_github_call(StorageStub(), "live", ok()), {"items": []})


class OperationRunTests(unittest.IsolatedAsyncioTestCase):
    async def test_successful_operation_is_completed_by_runner(self) -> None:
        operation = Operation(id="operation", kind="publisher-manage", stage="updating_repository")

        async def succeed() -> dict[str, str]:
            return {"result": "ok"}

        await _run(operation, succeed())
        self.assertEqual(operation.status, "success")
        self.assertEqual(operation.stage, "complete")
        self.assertEqual(operation.result, {"result": "ok"})

    async def test_failed_operation_retains_the_failed_stage(self) -> None:
        operation = Operation(id="operation", kind="publisher-manage", stage="updating_repository")

        async def fail() -> dict[str, str]:
            raise ValueError("commit failed")

        await _run(operation, fail())
        self.assertEqual(operation.status, "failed")
        self.assertEqual(operation.stage, "failed")
        self.assertEqual(operation.metadata["failed_stage"], "updating_repository")


class DependencyOperationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncTearDown(self) -> None:
        api_module._active_dependency_job = None

    async def test_revalidation_returns_current_keep_state_for_an_idempotent_retry(self) -> None:
        action = {
            "task_id": "git:https://github.com/example/pack",
            "name": "pack",
            "source_url": "https://github.com/example/pack",
            "requested": "a" * 40,
            "action": "install",
        }
        current = {**action, "action": "keep", "installed": "a" * 40}
        with patch.object(api_module, "_plan_dependencies", AsyncMock(return_value=[current])):
            result = await api_module._revalidate_dependency_actions([action], "align", "http://127.0.0.1:8188")
        self.assertEqual(result, [current])

    async def test_revalidation_preserves_the_specific_manual_action_error(self) -> None:
        action = {
            "task_id": "git:https://github.com/example/pack",
            "name": "pack",
            "source_url": "https://github.com/example/pack",
            "requested": "a" * 40,
            "action": "install",
        }
        current = {
            **action,
            "action": "manual",
            "warning_code": "dependencies.target_exists",
            "warning_params": {"path": "pack"},
        }
        with (
            patch.object(api_module, "_plan_dependencies", AsyncMock(return_value=[current])),
            self.assertRaises(UserFacingError) as caught,
        ):
            await api_module._revalidate_dependency_actions([action], "align", "http://127.0.0.1:8188")
        self.assertEqual(caught.exception.code, "dependencies.target_exists")
        self.assertEqual(caught.exception.params, {"path": "pack"})

    async def test_identical_active_request_reuses_the_same_operation(self) -> None:
        storage = StorageStub()
        metadata = {"workflow_key": "owner/repo/workflow/v1"}
        actions = [{"task_id": "git:pack", "requested": "a" * 40, "action": "install"}]
        signature = api_module._dependency_job_signature(metadata, actions, "align")
        operation = Operation(id="existing", kind="dependencies", owner_key=storage.key)
        api_module._active_dependency_job = (storage.key, signature, operation)

        with patch.object(api_module.operations, "create", AsyncMock()) as create:
            result = await api_module._schedule_dependency_operation(
                storage, metadata, actions, "align", "http://127.0.0.1:8188"
            )

        self.assertIs(result, operation)
        create.assert_not_awaited()

    async def test_different_dependency_request_is_rejected_while_environment_is_busy(self) -> None:
        storage = StorageStub()
        operation = Operation(id="existing", kind="dependencies", owner_key=storage.key)
        api_module._active_dependency_job = (storage.key, "other-signature", operation)
        with self.assertRaises(UserFacingError) as caught:
            await api_module._schedule_dependency_operation(
                storage,
                {"workflow_key": "workflow"},
                [{"task_id": "git:pack", "requested": "a" * 40, "action": "install"}],
                "align",
                "http://127.0.0.1:8188",
            )
        self.assertEqual(caught.exception.code, "dependencies.operation_busy")


class ResponseErrorTests(unittest.TestCase):
    def test_github_401_maps_to_http_401(self) -> None:
        response = _response_error(GitHubError("GitHub 登录已失效，请重新登录", 401))
        self.assertEqual(response.status, 401)

    def test_github_403_keeps_http_400(self) -> None:
        response = _response_error(GitHubError("Forbidden", 403))
        self.assertEqual(response.status, 400)

    def test_user_facing_errors_return_a_localization_code(self) -> None:
        response = _response_error(UserFacingError("publisher.lora_forbidden", {"count": 2}))
        self.assertEqual(response.status, 400)
        self.assertEqual(json.loads(response.text), {
            "error_code": "publisher.lora_forbidden",
            "error_params": {"count": 2},
        })

    def test_busy_dependency_environment_returns_conflict(self) -> None:
        response = _response_error(UserFacingError("dependencies.operation_busy"))
        self.assertEqual(response.status, 409)
        self.assertEqual(json.loads(response.text)["error_code"], "dependencies.operation_busy")
