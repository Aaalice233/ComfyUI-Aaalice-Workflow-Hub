import tempfile
from pathlib import Path
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import AsyncMock, patch

from workflow_hub import manager as manager_module
from workflow_hub.dependency_policy import is_ignored_dependency
from workflow_hub.legacy_manager import ManagerAdapter
from workflow_hub.manager import GitAdapter, GitRepository, _canonical_source, _requested_commit, local_git_status


COMMIT_A = "a" * 40
COMMIT_B = "b" * 40
SOURCE = "https://github.com/example/pack"
MANAGER_SOURCE = "https://github.com/ltdrdata/ComfyUI-Manager"
WORKFLOW_HUB_SOURCE = "https://github.com/Aaalice233/ComfyUI-Aaalice-Workflow-Hub"


class GitExecutableTests(TestCase):
    def test_detects_comfyui_xiao_portable_git(self):
        for relative_path in (("cmd", "git.exe"), ("bin", "git.exe"), ("mingw64", "bin", "git.exe")):
            with self.subTest(relative_path=relative_path), tempfile.TemporaryDirectory() as directory:
                install_root = Path(directory)
                comfyui_root = install_root / "ComfyUI"
                python = comfyui_root / "venv" / "Scripts" / "python.exe"
                git = install_root / ".xiaoziya" / "PortableGit" / Path(*relative_path)
                python.parent.mkdir(parents=True)
                python.touch()
                git.parent.mkdir(parents=True)
                git.touch()
                with (
                    patch.object(manager_module, "_comfyui_root", return_value=comfyui_root),
                    patch.object(manager_module.sys, "prefix", str(python.parents[1])),
                    patch.object(manager_module.sys, "executable", str(python)),
                    patch.object(manager_module.shutil, "which", return_value=None),
                ):
                    self.assertEqual(manager_module._git_executable(), str(git))

    def test_uses_git_from_process_path_as_fallback(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            comfyui_root = root / "ComfyUI"
            python = root / "python" / "python.exe"
            git = root / "tools" / "git.exe"
            comfyui_root.mkdir()
            python.parent.mkdir()
            python.touch()
            git.parent.mkdir()
            git.touch()
            with (
                patch.object(manager_module, "_comfyui_root", return_value=comfyui_root),
                patch.object(manager_module.sys, "prefix", str(python.parent)),
                patch.object(manager_module.sys, "executable", str(python)),
                patch.object(manager_module.shutil, "which", return_value=str(git)),
            ):
                self.assertEqual(manager_module._git_executable(), str(git))


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

    def test_plan_repairs_detached_matching_commit(self):
        repository = GitRepository("pack", Path("custom_nodes/pack"), SOURCE, COMMIT_A, False, True)
        dependency = {
            "name": "pack",
            "source_url": SOURCE,
            "commit": COMMIT_A,
            "manual": True,
        }
        with patch.object(manager_module, "_scan_repositories", AsyncMock(return_value=[repository])):
            result = self._run_plan([dependency])
        self.assertEqual(result[0]["action"], "upgrade")

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

    def test_plan_blocks_duplicate_git_sources(self):
        repositories = [
            GitRepository("pack-a", Path("custom_nodes/pack-a"), SOURCE, COMMIT_A, False),
            GitRepository("pack-b", Path("custom_nodes/pack-b"), SOURCE, COMMIT_B, False),
        ]
        dependency = {"name": "pack", "source_url": SOURCE, "commit": COMMIT_A, "manual": True}
        with patch.object(manager_module, "_scan_repositories", AsyncMock(return_value=repositories)):
            result = self._run_plan([dependency])
        self.assertEqual(result[0]["action"], "manual")
        self.assertEqual(result[0]["warning_code"], "dependencies.duplicate_git_source")

    def test_plan_skips_legacy_registry_dependency(self):
        dependency = {"registry_id": "old-pack", "name": "Old Pack", "version": "1.0.0", "manual": False}
        with patch.object(manager_module, "_scan_repositories", AsyncMock(return_value=[])):
            result = self._run_plan([dependency])
        self.assertEqual(result, [])

    def test_plan_skips_ignored_system_plugins(self):
        dependencies = [
            {"name": "ComfyUI-Manager", "source_url": MANAGER_SOURCE, "commit": COMMIT_A, "manual": True},
            {"name": "ComfyUI-Aaalice-Workflow-Hub", "source_url": WORKFLOW_HUB_SOURCE, "commit": COMMIT_A, "manual": True},
        ]
        with patch.object(manager_module, "_scan_repositories", AsyncMock()) as scan:
            result = self._run_plan(dependencies)
        self.assertEqual(result, [])
        scan.assert_not_awaited()

    def test_requested_commit_accepts_plan_output_field(self):
        # execute 收到的是 plan() 输出的字典，提交记录在 requested 字段
        self.assertEqual(_requested_commit({"requested": COMMIT_A}), COMMIT_A)
        self.assertEqual(_requested_commit({"commit": COMMIT_A}), COMMIT_A)
        self.assertEqual(_requested_commit({"commit": COMMIT_A.upper()}), COMMIT_A)
        self.assertEqual(_requested_commit({"version": COMMIT_A}), COMMIT_A)
        self.assertIsNone(_requested_commit({"requested": "1.0.0"}))
        self.assertIsNone(_requested_commit({}))

    def test_ignored_dependency_matches_source_and_identifier(self):
        self.assertTrue(is_ignored_dependency({"source_url": MANAGER_SOURCE}))
        self.assertTrue(is_ignored_dependency({"name": "ComfyUI Manager"}))
        self.assertTrue(is_ignored_dependency({"registry_id": "comfyui-manager"}))
        self.assertTrue(is_ignored_dependency({"source_url": WORKFLOW_HUB_SOURCE}))
        self.assertFalse(is_ignored_dependency({"name": "ComfyUI-Manager-Plus"}))

    async def _plan(self, dependencies):
        return await GitAdapter().plan(dependencies)

    def _run_plan(self, dependencies):
        import asyncio

        return asyncio.run(self._plan(dependencies))


class ManagerDependencyTests(IsolatedAsyncioTestCase):
    async def test_plan_skips_comfyui_manager(self):
        adapter = ManagerAdapter("http://127.0.0.1:8188")
        with patch.object(adapter, "_detect", AsyncMock()) as detect:
            result = await adapter.plan([{"registry_id": "comfyui-manager", "name": "ComfyUI-Manager", "version": "4.2.1"}])
        self.assertEqual(result, [])
        detect.assert_not_awaited()


class GitStatusTests(IsolatedAsyncioTestCase):
    def test_status_reports_git_source(self):
        with patch.object(manager_module, "_git_executable", return_value="git"):
            status = local_git_status()
        self.assertEqual(status["available"], True)
        self.assertEqual(status["source"], "github")
        self.assertIn("launcher_mirrors", status)

    async def test_installed_dependencies_are_locked_to_commits(self):
        repository = GitRepository("pack", Path("custom_nodes/pack"), SOURCE, COMMIT_A, False)
        with patch.object(manager_module, "_scan_repositories", AsyncMock(return_value=[repository])):
            result = await GitAdapter().installed_dependencies()
        self.assertEqual(result[0]["source_url"], SOURCE)
        self.assertEqual(result[0]["commit"], COMMIT_A)
        self.assertTrue(result[0]["manual"])

    async def test_installed_dependencies_skip_ignored_system_plugins(self):
        repositories = [
            GitRepository("ComfyUI-Manager", Path("custom_nodes/ComfyUI-Manager"), MANAGER_SOURCE, COMMIT_A, False),
            GitRepository("ComfyUI-Aaalice-Workflow-Hub", Path("custom_nodes/ComfyUI-Aaalice-Workflow-Hub"), WORKFLOW_HUB_SOURCE, COMMIT_A, False),
        ]
        with patch.object(manager_module, "_scan_repositories", AsyncMock(return_value=repositories)):
            result = await GitAdapter().installed_dependencies()
        self.assertEqual(result, [])
