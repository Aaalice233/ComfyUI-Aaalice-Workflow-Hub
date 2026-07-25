import json
import unittest
from datetime import datetime, timezone
from unittest import mock

from workflow_hub.catalog import Asset, Catalog, Repository, WorkflowProduct, WorkflowVersion
from workflow_hub.github import BranchState, GitTreeFile
from workflow_hub.service import delete_version, delete_workflow, update_version_changelog

SHA256 = "a" * 64


def make_product(versions: list[str]) -> WorkflowProduct:
    return WorkflowProduct(
        id="demo-flow",
        name="Demo",
        category="图像",
        summary="s",
        repository_path="workflows/图像/Demo",
        versions=[
            WorkflowVersion(
                version=value,
                published_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
                release_tag=f"demo-flow-v{value}",
                changelog=f"notes {value}",
                package=Asset(
                    url=f"https://github.com/owner/repo/releases/download/demo-flow-v{value}/p.zip",
                    size=10,
                    sha256=SHA256,
                ),
                repository_path=f"workflows/图像/Demo/versions/v{value}",
            )
            for value in versions
        ],
    )


def make_state_files(versions: list[str]) -> dict[str, GitTreeFile]:
    files = {
        "workflow-catalog.json": GitTreeFile("workflow-catalog.json", "100644", "catalog"),
        "workflows/README.md": GitTreeFile("workflows/README.md", "100644", "readme"),
        "workflows/图像/Demo/product.json": GitTreeFile("workflows/图像/Demo/product.json", "100644", "product"),
        "workflows/图像/Demo/README.md": GitTreeFile("workflows/图像/Demo/README.md", "100644", "product-readme"),
    }
    for value in versions:
        path = f"workflows/图像/Demo/versions/v{value}/workflow.json"
        files[path] = GitTreeFile(path, "100644", f"workflow-{value}")
    return files


class ManageClient:
    def __init__(self, catalog: Catalog, files: dict[str, GitTreeFile]) -> None:
        self.catalog = catalog
        self.files = files
        self.releases = {
            version.release_tag: {"id": 100 + index}
            for product in catalog.workflows
            for index, version in enumerate(product.versions)
        }
        self.deleted_releases: list[int] = []
        self.deleted_tags: list[str] = []
        self.notes_updates: list[tuple[int, str]] = []
        self.commits: list[dict] = []

    async def get_branch_state(self, owner: str, repo: str) -> BranchState:
        return BranchState(branch="main", commit_sha="c", tree_sha="t", files=self.files)

    async def read_file_from_state(self, owner: str, repo: str, state: BranchState, path: str):
        if path == "workflow-catalog.json":
            return json.dumps(self.catalog.model_dump(mode="json")).encode()
        return None

    async def get_release_by_tag(self, owner: str, repo: str, tag: str):
        return self.releases.get(tag)

    async def delete_release(self, owner: str, repo: str, release_id: int) -> None:
        self.deleted_releases.append(release_id)

    async def delete_tag(self, owner: str, repo: str, tag: str) -> None:
        self.deleted_tags.append(tag)

    async def update_release_notes(self, owner: str, repo: str, release_id: int, body: str) -> None:
        self.notes_updates.append((release_id, body))

    async def commit_files(self, owner, repo, state, files, message, *, delete_paths=None, copy_blobs=None) -> str:
        self.commits.append({"files": files, "message": message, "delete_paths": delete_paths or set()})
        return "new-commit"


def patched_client(client: ManageClient):
    return mock.patch("workflow_hub.service.GitHubClient", return_value=client)


def committed_catalog(client: ManageClient) -> dict:
    return json.loads(client.commits[-1]["files"]["workflow-catalog.json"])


class ManageTests(unittest.IsolatedAsyncioTestCase):
    async def test_delete_version_removes_release_tag_and_version_directory(self):
        client = ManageClient(Catalog(repository=Repository(name="repo", author="owner"), workflows=[make_product(["1.0", "2.0"])]), make_state_files(["1.0", "2.0"]))
        with patched_client(client):
            result = await delete_version("token", "owner", "repo", "demo-flow", "1.0")

        self.assertEqual(result, {"deleted_version": "1.0", "workflow_deleted": False})
        self.assertEqual(client.deleted_releases, [100])
        self.assertEqual(client.deleted_tags, ["demo-flow-v1.0"])
        versions = committed_catalog(client)["workflows"][0]["versions"]
        self.assertEqual([item["version"] for item in versions], ["2.0"])
        deleted = client.commits[-1]["delete_paths"]
        self.assertIn("workflows/图像/Demo/versions/v1.0/workflow.json", deleted)
        self.assertNotIn("workflows/图像/Demo/versions/v2.0/workflow.json", deleted)

    async def test_delete_last_version_removes_whole_workflow(self):
        client = ManageClient(Catalog(repository=Repository(name="repo", author="owner"), workflows=[make_product(["1.0"])]), make_state_files(["1.0"]))
        with patched_client(client):
            result = await delete_version("token", "owner", "repo", "demo-flow", "1.0")

        self.assertEqual(result, {"deleted_version": "1.0", "workflow_deleted": True})
        self.assertEqual(committed_catalog(client)["workflows"], [])
        deleted = client.commits[-1]["delete_paths"]
        self.assertIn("workflows/图像/Demo/product.json", deleted)
        self.assertIn("workflows/图像/Demo/versions/v1.0/workflow.json", deleted)

    async def test_delete_workflow_removes_every_release_and_product_directory(self):
        client = ManageClient(Catalog(repository=Repository(name="repo", author="owner"), workflows=[make_product(["1.0", "2.0"])]), make_state_files(["1.0", "2.0"]))
        with patched_client(client):
            result = await delete_workflow("token", "owner", "repo", "demo-flow")

        self.assertEqual(result, {"deleted_workflow": "demo-flow", "deleted_versions": 2})
        self.assertEqual(client.deleted_releases, [100, 101])
        self.assertEqual(client.deleted_tags, ["demo-flow-v1.0", "demo-flow-v2.0"])
        self.assertEqual(committed_catalog(client)["workflows"], [])
        self.assertIn("workflows/图像/Demo/README.md", client.commits[-1]["delete_paths"])

    async def test_delete_missing_version_fails(self):
        client = ManageClient(Catalog(repository=Repository(name="repo", author="owner"), workflows=[make_product(["1.0"])]), make_state_files(["1.0"]))
        with patched_client(client), self.assertRaisesRegex(ValueError, "版本不存在"):
            await delete_version("token", "owner", "repo", "demo-flow", "9.9")

    async def test_update_changelog_rewrites_release_notes_and_catalog(self):
        client = ManageClient(Catalog(repository=Repository(name="repo", author="owner"), workflows=[make_product(["1.0", "2.0"])]), make_state_files(["1.0", "2.0"]))
        with patched_client(client):
            result = await update_version_changelog("token", "owner", "repo", "demo-flow", "2.0", "new notes")

        self.assertEqual(client.notes_updates, [(101, "new notes")])
        self.assertEqual(result["changelog"], "new notes")
        versions = committed_catalog(client)["workflows"][0]["versions"]
        self.assertEqual([item["changelog"] for item in versions], ["notes 1.0", "new notes"])

    async def test_update_changelog_rejects_empty_text(self):
        client = ManageClient(Catalog(repository=Repository(name="repo", author="owner"), workflows=[make_product(["1.0"])]), make_state_files(["1.0"]))
        with patched_client(client), self.assertRaisesRegex(ValueError, "更新日志不能为空"):
            await update_version_changelog("token", "owner", "repo", "demo-flow", "1.0", "  ")
        self.assertEqual(client.notes_updates, [])
        self.assertEqual(client.commits, [])


if __name__ == "__main__":
    unittest.main()
