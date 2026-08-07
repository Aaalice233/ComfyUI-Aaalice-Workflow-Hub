import json
import tempfile
import unittest
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from workflow_hub.catalog import Asset, Catalog, NodeDependency, Repository, WorkflowProduct, WorkflowVersion
from workflow_hub.errors import UserFacingError
from workflow_hub.github import BranchState, GitTreeFile
from workflow_hub.packages import build_package_files, read_package_files, write_package
from workflow_hub.service import delete_version, delete_workflow, update_version_changelog, update_version_dependencies

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


COMMIT_OLD = "1" * 40
COMMIT_NEW = "2" * 40
COMMIT_UNKNOWN = "3" * 40
GIT_SOURCE = "https://github.com/someone/plugin-a"


class DependencyManageClient(ManageClient):
    def __init__(self, catalog: Catalog, files: dict[str, GitTreeFile], package_files: dict[str, bytes], known_commits: set[str]) -> None:
        super().__init__(catalog, files)
        self.package_files = package_files
        self.known_commits = known_commits
        self.deleted_assets: list[int] = []
        self.uploads: list[dict] = []
        for release in self.releases.values():
            release["assets"] = [{"id": 900, "name": "p.zip"}]
            release["upload_url"] = "https://uploads.github.com/repos/owner/repo/releases/1/assets{?name}"

    async def download(self, url: str, destination, operation=None) -> None:
        write_package(Path(destination), self.package_files)

    async def delete_release_asset(self, owner: str, repo: str, asset_id: int) -> None:
        self.deleted_assets.append(asset_id)

    async def upload_asset(self, upload_url: str, name: str, content: bytes, content_type: str) -> dict:
        self.uploads.append({"name": name, "content": content})
        return {"size": len(content), "digest": f"sha256:{hashlib.sha256(content).hexdigest()}"}

    async def get_commit(self, owner: str, repo: str, sha: str) -> bool:
        return sha in self.known_commits


class DependencyPinTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.storage_root = Path(self.tempdir.name)
        manifest = {
            "schema_version": 1,
            "workflow_id": "demo-flow",
            "custom_nodes": [
                {"name": "PluginA", "source_url": GIT_SOURCE, "commit": COMMIT_OLD, "registry_id": None, "version": None, "required": True, "manual": True},
            ],
            "models": [],
            "inputs": [],
        }
        self.package_files = build_package_files(manifest, {"nodes": []}, "notes 1.0")
        package_path = self.storage_root / "original.zip"
        self.package_info = write_package(package_path, self.package_files)

    def make_client(self, known_commits: set[str]) -> DependencyManageClient:
        product = WorkflowProduct(
            id="demo-flow",
            name="Demo",
            category="图像",
            summary="s",
            repository_path="workflows/图像/Demo",
            versions=[
                WorkflowVersion(
                    version="1.0",
                    published_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
                    release_tag="demo-flow-v1.0",
                    changelog="notes 1.0",
                    package=Asset(
                        url="https://github.com/owner/repo/releases/download/demo-flow-v1.0/p.zip",
                        size=self.package_info["size"],
                        sha256=self.package_info["sha256"],
                    ),
                    custom_nodes=[
                        NodeDependency(name="PluginA", source_url=GIT_SOURCE, commit=COMMIT_OLD, manual=True),
                        NodeDependency(name="PluginB", registry_id="plugin-b", version="1.0.0"),
                    ],
                    repository_path="workflows/图像/Demo/versions/v1.0",
                )
            ],
        )
        catalog = Catalog(repository=Repository(name="repo", author="owner"), workflows=[product])
        return DependencyManageClient(catalog, make_state_files(["1.0"]), self.package_files, known_commits)

    async def run_update(self, client: DependencyManageClient, updates: list[dict]) -> dict:
        from workflow_hub.storage import UserStorage

        with patched_client(client):
            return await update_version_dependencies(
                UserStorage(self.storage_root / "user"), "token", "owner", "repo", "demo-flow", "1.0", updates
            )

    async def test_update_dependency_repins_catalog_and_package(self):
        client = self.make_client({COMMIT_OLD, COMMIT_NEW})
        result = await self.run_update(client, [{"source_url": GIT_SOURCE, "commit": COMMIT_NEW}])

        nodes = {item["name"]: item for item in result["custom_nodes"]}
        self.assertEqual(nodes["PluginA"]["commit"], COMMIT_NEW)
        self.assertEqual(nodes["PluginB"]["registry_id"], "plugin-b")
        committed_nodes = {item["name"]: item for item in committed_catalog(client)["workflows"][0]["versions"][0]["custom_nodes"]}
        self.assertEqual(committed_nodes["PluginA"]["commit"], COMMIT_NEW)
        committed_manifest = json.loads(client.commits[-1]["files"]["workflows/图像/Demo/versions/v1.0/manifest.json"])
        self.assertEqual(committed_manifest["custom_nodes"][0]["commit"], COMMIT_NEW)
        self.assertEqual(client.deleted_assets, [900])
        self.assertEqual(len(client.uploads), 1)
        uploaded_zip = self.storage_root / "uploaded.zip"
        uploaded_zip.write_bytes(client.uploads[0]["content"])
        manifest = json.loads(read_package_files(uploaded_zip)["manifest.json"].decode())
        self.assertEqual(manifest["custom_nodes"][0]["commit"], COMMIT_NEW)
        self.assertEqual(result["package"]["sha256"], hashlib.sha256(client.uploads[0]["content"]).hexdigest())

    async def test_update_dependency_without_change_fails(self):
        client = self.make_client({COMMIT_OLD})
        with self.assertRaises(UserFacingError) as ctx:
            await self.run_update(client, [{"source_url": GIT_SOURCE, "commit": COMMIT_OLD}])
        self.assertEqual(str(ctx.exception), "publisher.dependency_update_invalid")
        self.assertEqual(client.commits, [])

    async def test_update_dependency_rejects_unknown_source(self):
        client = self.make_client({COMMIT_NEW})
        with self.assertRaises(UserFacingError):
            await self.run_update(client, [{"source_url": "https://github.com/someone/other", "commit": COMMIT_NEW}])
        self.assertEqual(client.commits, [])

    async def test_update_dependency_rejects_missing_commit(self):
        client = self.make_client({COMMIT_OLD})
        with self.assertRaises(UserFacingError) as ctx:
            await self.run_update(client, [{"source_url": GIT_SOURCE, "commit": COMMIT_UNKNOWN}])
        self.assertEqual(str(ctx.exception), "publisher.dependency_commit_missing")
        self.assertEqual(ctx.exception.params, {"name": "PluginA", "commit": COMMIT_UNKNOWN[:12]})
        self.assertEqual(client.commits, [])

    async def test_update_dependency_rejects_invalid_commit(self):
        client = self.make_client({COMMIT_NEW})
        with self.assertRaises(UserFacingError):
            await self.run_update(client, [{"source_url": GIT_SOURCE, "commit": "abc"}])
        self.assertEqual(client.uploads, [])


if __name__ == "__main__":
    unittest.main()
