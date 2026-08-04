import json
import unittest

from aiohttp import web

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

    async def test_401_clears_stored_credential(self) -> None:
        tokens._session_tokens[StorageStub.key] = '{"access_token": "dead"}'

        async def fail():
            raise GitHubError("Bad credentials", 401)

        with self.assertRaisesRegex(GitHubError, "重新登录") as caught:
            await _guarded_github_call(StorageStub(), fail())
        self.assertEqual(caught.exception.status, 401)
        self.assertIsNone(await tokens.get(StorageStub.key))

    async def test_other_errors_keep_credential(self) -> None:
        tokens._session_tokens[StorageStub.key] = '{"access_token": "live"}'

        async def fail():
            raise GitHubError("boom", 500)

        with self.assertRaises(GitHubError):
            await _guarded_github_call(StorageStub(), fail())
        self.assertEqual(await tokens.get(StorageStub.key), "live")

    async def test_result_passes_through(self) -> None:
        async def ok():
            return {"items": []}

        self.assertEqual(await _guarded_github_call(StorageStub(), ok()), {"items": []})


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
