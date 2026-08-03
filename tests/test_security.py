import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from workflow_hub.security import ensure_within, parse_public_repository, redact, require_github_https, safe_filename


class SecurityTests(unittest.TestCase):
    def test_repository_parser(self):
        self.assertEqual(parse_public_repository("https://github.com/owner/repo"), ("owner", "repo"))
        self.assertEqual(parse_public_repository("  https://github.com/owner/repo  "), ("owner", "repo"))
        with self.assertRaises(ValueError):
            parse_public_repository("https://example.com/owner/repo")

    def test_url_allowlist(self):
        self.assertEqual(require_github_https("https://api.github.com/repos/a/b"), "https://api.github.com/repos/a/b")
        self.assertEqual(require_github_https("https://uploads.github.com/repos/a/b/releases/1/assets"), "https://uploads.github.com/repos/a/b/releases/1/assets")
        self.assertEqual(require_github_https("https://raw.githubusercontent.com/owner/repo/HEAD/workflow-catalog.json"), "https://raw.githubusercontent.com/owner/repo/HEAD/workflow-catalog.json")
        for value in ("http://github.com/a/b", "https://evil.example/a.zip", "https://token@github.com/a/b"):
            with self.assertRaises(ValueError):
                require_github_https(value)

    def test_filename_and_containment(self):
        self.assertEqual(safe_filename('a:b/c*'), "a_b_c_")
        with TemporaryDirectory() as folder:
            with self.assertRaises(ValueError):
                ensure_within(Path(folder), Path(folder) / ".." / "escape")

    def test_redacts_credentials(self):
        text = 'Authorization: Bearer ghp_secret access_token="token" device_code=abc'
        cleaned = redact(text)
        self.assertNotIn("ghp_secret", cleaned)
        self.assertNotIn('"token"', cleaned)
        self.assertNotIn("=abc", cleaned)
