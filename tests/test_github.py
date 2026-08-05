import base64
import unittest

from workflow_hub.github import BranchState, GitHubClient, GitHubError, GitTreeFile, TokenStore


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


class GitDataClient(GitHubClient):
    def __init__(self):
        super().__init__("token")
        self.calls = []

    async def request(self, method: str, url: str, **kwargs):
        self.calls.append((method, url, kwargs))
        if url.endswith("/git/blobs") and method == "POST":
            return {"sha": "new-blob"}, {}
        if url.endswith("/git/trees") and method == "POST":
            return {"sha": "new-tree"}, {}
        if url.endswith("/git/commits") and method == "POST":
            return {"sha": "new-commit"}, {}
        if "/git/refs/heads/" in url and method == "PATCH":
            return {"ref": "refs/heads/main"}, {}
        raise AssertionError((method, url))


class CatalogClient(GitHubClient):
    def __init__(self):
        super().__init__()
        self.call = None

    async def request(self, method: str, url: str, **kwargs):
        self.call = (method, url, kwargs)
        return {"content": base64.b64encode(b"{}").decode(), "sha": "blob-sha"}, {"ETag": '"api-etag"'}


class RateLimitedCatalogClient(GitHubClient):
    def __init__(self):
        super().__init__()
        self.calls = []

    async def request(self, method: str, url: str, **kwargs):
        self.calls.append((method, url, kwargs))
        if url.startswith("https://api.github.com/"):
            raise GitHubError(
                "API rate limit exceeded for 192.0.2.1",
                403,
                {"message": "API rate limit exceeded for 192.0.2.1"},
            )
        return b"{}", {"ETag": 'W/"raw-etag"'}


class ForbiddenCatalogClient(GitHubClient):
    async def request(self, method: str, url: str, **kwargs):
        raise GitHubError("Repository access blocked", 403, {"message": "Repository access blocked"})


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

    async def test_reads_catalog_from_github_contents_api(self):
        client = CatalogClient()

        result = await client.get_catalog("owner", "repo", '"old-etag"')

        self.assertEqual(result.content, b"{}")
        self.assertEqual(result.sha, "blob-sha")
        self.assertEqual(result.etag, '"api-etag"')
        self.assertEqual(client.call[0], "GET")
        self.assertEqual(
            client.call[1],
            "https://api.github.com/repos/owner/repo/contents/workflow-catalog.json",
        )
        self.assertEqual(client.call[2]["headers"], {"If-None-Match": '"old-etag"'})

    async def test_catalog_304_is_reported_as_not_modified(self):
        result = await GitHubClient(session=NotModifiedSession()).get_catalog("owner", "repo", '"catalog-etag"')

        self.assertTrue(result.not_modified)
        self.assertEqual(result.etag, '"catalog-etag"')

    async def test_catalog_rate_limit_falls_back_to_forced_raw_request(self):
        client = RateLimitedCatalogClient()

        result = await client.get_catalog("owner", "repo", force=True)

        self.assertEqual(result.content, b"{}")
        self.assertEqual(result.etag, 'W/"raw-etag"')
        self.assertEqual(len(client.calls), 2)
        self.assertTrue(client.calls[0][1].startswith("https://api.github.com/repos/owner/repo/contents/"))
        raw_call = client.calls[1]
        self.assertTrue(raw_call[1].startswith("https://raw.githubusercontent.com/owner/repo/HEAD/workflow-catalog.json?"))
        self.assertEqual(raw_call[2]["headers"], {"Cache-Control": "no-cache"})

    async def test_catalog_forbidden_error_does_not_fall_back_to_raw(self):
        with self.assertRaisesRegex(GitHubError, "Repository access blocked"):
            await ForbiddenCatalogClient().get_catalog("owner", "repo")

    async def test_forced_catalog_refresh_bypasses_conditional_cache(self):
        client = CatalogClient()

        await client.get_catalog("owner", "repo", '"old-etag"', force=True)

        self.assertEqual(client.call[2]["headers"], {"Cache-Control": "no-cache"})

    async def test_token_remains_in_session_when_keyring_read_fails(self):
        store = TokenStore()
        store._keyring = WriteOnlyKeyring()

        await store.set("user", {"access_token": "secret"})

        self.assertEqual(await store.get("user"), "secret")

    async def test_commits_multiple_repository_files_with_one_ref_update(self):
        client = GitDataClient()
        state = BranchState(
            branch="main",
            commit_sha="old-commit",
            tree_sha="old-tree",
            files={},
        )

        result = await client.commit_files(
            "owner",
            "repo",
            state,
            {"workflow-catalog.json": b"{}", "workflows/A/B/product.json": b"{}"},
            "Publish",
            delete_paths={"workflows/Old/B/product.json"},
            copy_blobs={
                "workflows/A/B/versions/v1.0/workflow.json": GitTreeFile(
                    "workflows/Old/B/versions/v1.0/workflow.json",
                    "100644",
                    "existing-blob",
                )
            },
        )

        self.assertEqual(result, "new-commit")
        tree_call = next(call for call in client.calls if call[1].endswith("/git/trees"))
        entries = tree_call[2]["json"]["tree"]
        self.assertEqual(tree_call[2]["json"]["base_tree"], "old-tree")
        self.assertTrue(any(item["sha"] is None for item in entries))
        self.assertTrue(any(item["sha"] == "existing-blob" for item in entries))
        ref_calls = [call for call in client.calls if "/git/refs/heads/" in call[1]]
        self.assertEqual(len(ref_calls), 1)
        self.assertEqual(ref_calls[0][2]["json"], {"sha": "new-commit", "force": False})


if __name__ == "__main__":
    unittest.main()
