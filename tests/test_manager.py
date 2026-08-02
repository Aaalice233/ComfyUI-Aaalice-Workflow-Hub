from pathlib import Path
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, patch

from workflow_hub import manager as manager_module
from workflow_hub.manager import GitAdapter, GitRepository, _canonical_source, local_git_status


COMMIT_A = "a" * 40
COMMIT_B = "b" * 40
SOURCE = "https://github.com/example/pack"


class GitSourceTests(IsolatedAsyncioTestCase):
    def test_canonical_source_accepts_public_github_forms(self):
        self.assertEqual(_canonical_source("https://github.com/example/pack.git"), SOURCE)
        self.assertEqual(_canonical_source("example/pack"), SOURCE)

    def test_plan_keeps_matching_commit(self):
        repository = GitRepository("pack", Path("custom_nodes/pack"), SOURCE, COMMIT_A, False)
        dependency = {
            "name": "pack",
            "source_url": SOURCE,
            "commit": COMMIT_A,
            "manual": True,
        }
        with patch.object(manager_module, "_scan_repositories", AsyncMock(return_value=[repository])):
            result = self._run_plan([dependency])
        self.assertEqual(result[0]["action"], "keep")
        self.assertEqual(result[0]["installed"], COMMIT_A)
        self.assertEqual(result[0]["requested"], COMMIT_A)

    def test_plan_requests_switch_for_different_clean_commit(self):
        repository = GitRepository("pack", Path("custom_nodes/pack"), SOURCE, COMMIT_A, False)
        dependency = {"name": "pack", "source_url": SOURCE, "commit": COMMIT_B, "manual": True}
        with patch.object(manager_module, "_scan_repositories", AsyncMock(return_value=[repository])):
            result = self._run_plan([dependency])
        self.assertEqual(result[0]["action"], "upgrade")

    def test_plan_blocks_dirty_repository(self):
        repository = GitRepository("pack", Path("custom_nodes/pack"), SOURCE, COMMIT_A, True)
        dependency = {"name": "pack", "source_url": SOURCE, "commit": COMMIT_B, "manual": True}
        with patch.object(manager_module, "_scan_repositories", AsyncMock(return_value=[repository])):
            result = self._run_plan([dependency])
        self.assertEqual(result[0]["action"], "manual")
        self.assertEqual(result[0]["warning_code"], "dependencies.local_changes")

    def test_plan_skips_legacy_registry_dependency(self):
        dependency = {"registry_id": "old-pack", "name": "Old Pack", "version": "1.0.0", "manual": False}
        with patch.object(manager_module, "_scan_repositories", AsyncMock(return_value=[])):
            result = self._run_plan([dependency])
        self.assertEqual(result, [])

    async def _plan(self, dependencies):
        return await GitAdapter().plan(dependencies)

    def _run_plan(self, dependencies):
        import asyncio

        return asyncio.run(self._plan(dependencies))


class GitStatusTests(IsolatedAsyncioTestCase):
    def test_status_reports_git_source(self):
        with patch.object(manager_module, "_git_executable", return_value="git"):
            self.assertEqual(local_git_status(), {"available": True, "source": "github"})

    async def test_installed_dependencies_are_locked_to_commits(self):
        repository = GitRepository("pack", Path("custom_nodes/pack"), SOURCE, COMMIT_A, False)
        with patch.object(manager_module, "_scan_repositories", AsyncMock(return_value=[repository])):
            result = await GitAdapter().installed_dependencies()
        self.assertEqual(result[0]["source_url"], SOURCE)
        self.assertEqual(result[0]["commit"], COMMIT_A)
        self.assertTrue(result[0]["manual"])
