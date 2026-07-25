import unittest

from workflow_hub.api import _json


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
