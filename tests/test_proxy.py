import os
import unittest
from unittest import mock

from workflow_hub import proxy


class ProxyParseTest(unittest.TestCase):
    def test_single_address_applies_to_http_and_https(self):
        self.assertEqual(
            proxy._parse_proxy_server("127.0.0.1:7890"),
            {"http": "http://127.0.0.1:7890", "https": "http://127.0.0.1:7890"},
        )

    def test_grouped_schemes(self):
        result = proxy._parse_proxy_server("http=127.0.0.1:7890;https=127.0.0.1:7891")
        self.assertEqual(result["http"], "http://127.0.0.1:7890")
        self.assertEqual(result["https"], "http://127.0.0.1:7891")
        self.assertNotIn("all", result)

    def test_socks_becomes_all_proxy(self):
        result = proxy._parse_proxy_server("socks=127.0.0.1:1080")
        self.assertEqual(result["all"], "socks5h://127.0.0.1:1080")
        self.assertEqual(result["http"], "socks5h://127.0.0.1:1080")
        self.assertEqual(result["https"], "socks5h://127.0.0.1:1080")

    def test_existing_scheme_preserved(self):
        result = proxy._parse_proxy_server("http://proxy.local:3128")
        self.assertEqual(result["http"], "http://proxy.local:3128")

    def test_empty_or_invalid(self):
        self.assertEqual(proxy._parse_proxy_server(""), {})
        self.assertEqual(proxy._parse_proxy_server("ftp=1.2.3.4:21"), {})

    def test_override_parsing(self):
        self.assertEqual(
            proxy._parse_proxy_override("localhost;127.*;*.LOCAL;<local>"),
            ["localhost", "127.*", ".local"],
        )
        self.assertEqual(proxy._parse_proxy_override("*zhihu.com"), ["zhihu.com"])

    def test_mask_credentials(self):
        self.assertEqual(
            proxy._mask_proxy_url("http://user:pass@127.0.0.1:7890"),
            "http://***@127.0.0.1:7890",
        )
        self.assertEqual(proxy._mask_proxy_url("http://127.0.0.1:7890"), "http://127.0.0.1:7890")


class ApplySystemProxyTest(unittest.TestCase):
    def setUp(self):
        proxy._status = None
        self._env_patcher = mock.patch.dict(os.environ, {}, clear=True)
        self._env_patcher.start()

    def tearDown(self):
        self._env_patcher.stop()
        proxy._status = None

    def test_environment_variables_take_precedence(self):
        os.environ["HTTPS_PROXY"] = "http://env-proxy:8080"
        with mock.patch.object(proxy, "_windows_system_proxy", return_value={"proxies": {"http": "http://sys:1", "https": "http://sys:1"}, "bypass": []}):
            status = proxy.apply_system_proxy()
        self.assertEqual(status["source"], "environment")
        self.assertEqual(status["proxies"], {"https": "http://env-proxy:8080"})
        self.assertNotIn("HTTP_PROXY", os.environ)

    def test_system_proxy_applied_with_local_bypass(self):
        with mock.patch.object(
            proxy,
            "_windows_system_proxy",
            return_value={"proxies": {"http": "http://127.0.0.1:7890", "https": "http://127.0.0.1:7890"}, "bypass": ["*.local"]},
        ):
            status = proxy.apply_system_proxy()
        self.assertTrue(status["enabled"])
        self.assertEqual(status["source"], "system")
        self.assertEqual(os.environ["HTTPS_PROXY"], "http://127.0.0.1:7890")
        self.assertEqual(os.environ["https_proxy"], "http://127.0.0.1:7890")
        bypass = os.environ["NO_PROXY"]
        for entry in ("*.local", "localhost", "127.0.0.1", "::1"):
            self.assertIn(entry, bypass)

    def test_no_system_proxy(self):
        with mock.patch.object(proxy, "_windows_system_proxy", return_value=None):
            status = proxy.apply_system_proxy()
        self.assertFalse(status["enabled"])
        self.assertIsNone(status["source"])
        self.assertNotIn("HTTPS_PROXY", os.environ)

    def test_idempotent(self):
        with mock.patch.object(proxy, "_windows_system_proxy", return_value={"proxies": {"http": "http://127.0.0.1:7890"}, "bypass": []}):
            first = proxy.apply_system_proxy()
            os.environ["HTTP_PROXY"] = "http://changed:1"
            second = proxy.apply_system_proxy()
        self.assertIs(first, second)
        self.assertEqual(os.environ["HTTP_PROXY"], "http://changed:1")


if __name__ == "__main__":
    unittest.main()
