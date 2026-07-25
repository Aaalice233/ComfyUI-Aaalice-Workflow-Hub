import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock, patch

from workflow_hub.catalog import Catalog
from workflow_hub.github import BranchState, GitHubError, GitTreeFile
from workflow_hub.operations import Operation
from workflow_hub.packages import build_package_files, write_package
from workflow_hub.repository import build_repository_files
from workflow_hub.service import _commit_publication, _relocation_changes, resume_publication
from workflow_hub.storage import UserStorage


ROOT = Path(__file__).resolve().parents[1]


class RepositoryLayoutTests(unittest.TestCase):
    def setUp(self) -> None:
        self.catalog = Catalog.model_validate_json(
            (ROOT / "examples/valid/workflow-catalog.json").read_bytes()
        )
        self.product = self.catalog.workflows[0]
        self.version = self.product.versions[0]

    def test_version_directory_uses_exact_package_source_files(self):
        package_files = build_package_files(
            {"schema_version": 1, "workflow_id": self.product.id, "inputs": []},
            {"nodes": []},
            "Initial release.",
        )

        files = build_repository_files(
            self.catalog,
            self.product,
            self.version,
            package_files,
        )

        prefix = f"{self.version.repository_path}/"
        for name, content in package_files.items():
            self.assertEqual(files[f"{prefix}{name}"], content)
        product = json.loads(files[f"{self.product.repository_path}/product.json"])
        self.assertEqual(product["id"], self.product.id)
        self.assertIn(b"workflow.json", files[f"{self.product.repository_path}/README.md"])
        self.assertIn(b"Portrait Basic", files["workflows/README.md"])

    def test_rename_moves_existing_blobs_and_deletes_old_paths(self):
        old_path = "workflows/Old/Workflow"
        source_path = f"{old_path}/versions/v1.0/workflow.json"
        state = BranchState(
            branch="main",
            commit_sha="commit",
            tree_sha="tree",
            files={
                source_path: GitTreeFile(source_path, "100644", "blob"),
                f"{old_path}/README.md": GitTreeFile(f"{old_path}/README.md", "100644", "readme"),
            },
        )
        new_path = "workflows/New/Workflow"
        writes = {f"{new_path}/README.md": b"generated"}

        deleted, copied = _relocation_changes(state, old_path, new_path, writes)

        self.assertEqual(deleted, set(state.files))
        self.assertEqual(
            copied[f"{new_path}/versions/v1.0/workflow.json"].sha,
            "blob",
        )
        self.assertNotIn(f"{new_path}/README.md", copied)

    def test_existing_version_directory_is_immutable(self):
        path = f"{self.version.repository_path}/workflow.json"
        state = BranchState(
            branch="main",
            commit_sha="commit",
            tree_sha="tree",
            files={path: GitTreeFile(path, "100644", "blob")},
        )

        with self.assertRaisesRegex(ValueError, "已经存在"):
            _relocation_changes(
                state,
                None,
                self.product.repository_path,
                {"workflow-catalog.json": b"{}"},
            )


class PublicationCommitTests(unittest.IsolatedAsyncioTestCase):
    async def test_publication_retries_one_non_fast_forward_and_commits_all_files(self):
        catalog = Catalog.model_validate_json(
            (ROOT / "examples/valid/workflow-catalog.json").read_bytes()
        )
        existing = catalog.workflows[0]
        next_version = existing.versions[0].model_copy(
            update={
                "version": "1.13",
                "release_tag": f"{existing.id}-v1.13",
                "repository_path": f"{existing.repository_path}/versions/v1.13",
            }
        )
        incoming = existing.model_copy(update={"versions": [next_version]})
        catalog_bytes = (catalog.model_dump_json(indent=2) + "\n").encode()
        state = BranchState(
            branch="main",
            commit_sha="commit",
            tree_sha="tree",
            files={
                "workflow-catalog.json": GitTreeFile("workflow-catalog.json", "100644", "catalog"),
            },
        )

        class Client:
            def __init__(self):
                self.commits = []

            async def get_branch_state(self, *_):
                return state

            async def read_file_from_state(self, *_):
                return catalog_bytes

            async def commit_files(self, *args, **kwargs):
                self.commits.append((args, kwargs))
                if len(self.commits) == 1:
                    raise GitHubError("non-fast-forward", 422)
                return "new-commit"

        client = Client()
        committed = await _commit_publication(
            client,
            "owner",
            "repo",
            catalog.repository.model_dump(mode="json"),
            incoming,
            {
                "manifest.json": b"{}",
                "workflow.json": b"{}",
                "CHANGELOG.md": b"Next.",
            },
        )

        self.assertEqual(len(client.commits), 2)
        files = client.commits[-1][0][3]
        self.assertIn("workflow-catalog.json", files)
        self.assertIn(f"{next_version.repository_path}/workflow.json", files)
        self.assertEqual(committed.versions[-1].version, "1.13")

    async def test_pending_publication_resumes_from_saved_package(self):
        catalog = Catalog.model_validate_json(
            (ROOT / "examples/valid/workflow-catalog.json").read_bytes()
        )
        product = catalog.workflows[0].model_copy(update={"versions": [catalog.workflows[0].versions[0]]})
        package_files = build_package_files(
            {"schema_version": 1, "workflow_id": product.id, "inputs": []},
            {"nodes": []},
            "Initial release.",
        )
        with TemporaryDirectory() as folder:
            storage = UserStorage(Path(folder))
            draft_name = "pending-package.zip"
            built = write_package(storage.drafts_dir / draft_name, package_files)
            product.versions[0].package.sha256 = built["sha256"]
            record = {
                "owner": "owner",
                "repo": "repo",
                "tag": product.versions[0].release_tag,
                "repository": catalog.repository.model_dump(mode="json"),
                "product": product.model_dump(mode="json"),
                "draft_name": draft_name,
                "release_url": "https://github.com/owner/repo/releases/tag/example",
            }
            await storage.write_json("pending_publications.json", [record])
            commit = AsyncMock(return_value=product)

            with (
                patch("workflow_hub.service.GitHubClient", return_value=object()),
                patch("workflow_hub.service._commit_publication", commit),
            ):
                result = await resume_publication(
                    storage,
                    "token",
                    record,
                    Operation(id="resume", kind="publish-resume"),
                )

            self.assertEqual(result["workflow_id"], product.id)
            self.assertFalse((storage.drafts_dir / draft_name).exists())
            self.assertEqual(await storage.read_json("pending_publications.json", []), [])
            version_files = commit.await_args.args[-1]
            self.assertEqual(version_files["workflow.json"], package_files["workflow.json"])


if __name__ == "__main__":
    unittest.main()
