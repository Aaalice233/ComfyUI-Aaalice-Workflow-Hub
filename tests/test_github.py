import unittest

from workflow_hub.github import GitHubClient, TokenStore


class NotModifiedResponse:
    status = 304
    headers = {"ETag": '"catalog-etag"'}
    content_type = "application/json"

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return None

    async def json(self):
        raise AssertionError("304 response body must not be parsed")


class NotModifiedSession:
    def request(self, *_args, **_kwargs):
        return NotModifiedResponse()


class InstallationGitHubClient(GitHubClient):
    async def request(self, method: str, url: str, **kwargs):
        if url.endswith("/user/installations?per_page=100"):
            return {"installations": [{"id": 20}, {"id": 10}]}, {}
        if "/user/installations/20/" in url:
            return {
                "repositories": [
                    {"id": 2, "full_name": "owner/private", "name": "private", "owner": {"login": "owner"}, "description": None, "default_branch": "main", "private": True},
                    {"id": 1, "full_name": "owner/Zeta", "name": "Zeta", "owner": {"login": "owner"}, "description": "Catalog", "default_branch": "main", "private": False},
                ]
            }, {}
        if "/user/installations/10/" in url:
            return {
                "repositories": [
                    {"id": 1, "full_name": "owner/Zeta", "name": "Zeta", "owner": {"login": "owner"}, "description": "Catalog", "default_branch": "main", "private": False},
                    {"id": 3, "full_name": "owner/alpha", "name": "alpha", "owner": {"login": "owner"}, "description": None, "default_branch": "trunk", "private": False},
                ]
            }, {}
        raise AssertionError(url)


class WriteOnlyKeyring:
    def set_password(self, *_args):
        return None

    def get_password(self, *_args):
        raise RuntimeError("credential backend temporarily unavailable")


class GitHubTests(unittest.IsolatedAsyncioTestCase):
    async def test_expected_not_modified_response_is_not_treated_as_redirect(self):
        data, headers = await GitHubClient(session=NotModifiedSession()).request(
            "GET",
            "https://api.github.com/repos/owner/repo/contents/workflow-catalog.json",
            expected=(200, 304),
        )
        self.assertIsNone(data)
        self.assertEqual(headers["ETag"], '"catalog-etag"')

    async def test_lists_only_public_installation_repositories(self):
        items = await InstallationGitHubClient("token").list_repositories()
        self.assertEqual([item["full_name"] for item in items], ["owner/alpha", "owner/Zeta"])
        self.assertEqual(items[0]["default_branch"], "trunk")
        self.assertEqual(items[1]["description"], "Catalog")

    async def test_token_remains_in_session_when_keyring_read_fails(self):
        store = TokenStore()
        store._keyring = WriteOnlyKeyring()

        await store.set("user", {"access_token": "secret"})

        self.assertEqual(await store.get("user"), "secret")


if __name__ == "__main__":
    unittest.main()
