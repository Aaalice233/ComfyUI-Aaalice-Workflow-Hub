import unittest

from workflow_hub.github import GitHubClient


class InstallationGitHubClient(GitHubClient):
    async def request(self, method: str, url: str, **kwargs):
        if url.endswith("/user/installations?per_page=100"):
            return {"installations": [{"id": 20}, {"id": 10}]}, {}
        if "/user/installations/20/" in url:
            return {
                "repositories": [
                    {"id": 2, "full_name": "owner/private", "default_branch": "main", "private": True},
                    {"id": 1, "full_name": "owner/Zeta", "default_branch": "main", "private": False},
                ]
            }, {}
        if "/user/installations/10/" in url:
            return {
                "repositories": [
                    {"id": 1, "full_name": "owner/Zeta", "default_branch": "main", "private": False},
                    {"id": 3, "full_name": "owner/alpha", "default_branch": "trunk", "private": False},
                ]
            }, {}
        raise AssertionError(url)


class GitHubTests(unittest.IsolatedAsyncioTestCase):
    async def test_lists_only_public_installation_repositories(self):
        items = await InstallationGitHubClient("token").list_repositories()
        self.assertEqual([item["full_name"] for item in items], ["owner/alpha", "owner/Zeta"])
        self.assertEqual(items[0]["default_branch"], "trunk")


if __name__ == "__main__":
    unittest.main()
