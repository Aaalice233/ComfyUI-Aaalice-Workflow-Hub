import unittest

from workflow_hub.api import _guarded_github_call, _json, _response_error
from workflow_hub.github import GitHubError, tokens


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


class JsonRequestTests(unittest.IsolatedAsyncioTestCase):
    async def test_empty_write_body_does_not_require_content_type(self) -> None:
        self.assertEqual(await _json(RequestStub(b"")), {})

    async def test_non_empty_body_requires_json_content_type(self) -> None:
        with self.assertRaisesRegex(ValueError, "application/json"):
            await _json(RequestStub(b"{}", "text/plain"))

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


class ResponseErrorTests(unittest.TestCase):
    def test_github_401_maps_to_http_401(self) -> None:
        response = _response_error(GitHubError("GitHub 登录已失效，请重新登录", 401))
        self.assertEqual(response.status, 401)

    def test_github_403_keeps_http_400(self) -> None:
        response = _response_error(GitHubError("Forbidden", 403))
        self.assertEqual(response.status, 400)
