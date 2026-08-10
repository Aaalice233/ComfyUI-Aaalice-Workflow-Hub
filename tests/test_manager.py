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

    def test_plan_repairs_dirty_repository(self):
        repository = GitRepository("pack", Path("custom_nodes/pack"), SOURCE, COMMIT_A, True)
        dependency = {"name": "pack", "source_url": SOURCE, "commit": COMMIT_B, "manual": True}
        with patch.object(manager_module, "_scan_repositories", AsyncMock(return_value=[repository])):
            result = self._run_plan([dependency])
        self.assertEqual(result[0]["action"], "upgrade")
        self.assertIsNone(result[0]["warning_code"])

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

    def test_plan_blocks_same_name_non_git_install(self):
        dependency = {"name": "pack", "source_url": SOURCE, "commit": COMMIT_A, "manual": True}
        with tempfile.TemporaryDirectory() as directory:
            custom_nodes = Path(directory) / "custom_nodes"
            marker = custom_nodes / "pack" / ".git" / ".cnr-id"
            marker.parent.mkdir(parents=True)
            marker.write_text("pack", encoding="utf-8")
            with (
                patch.object(manager_module, "_scan_repositories", AsyncMock(return_value=[])),
                patch.object(manager_module, "_custom_node_roots", return_value=[custom_nodes]),
            ):
                result = self._run_plan([dependency])
        self.assertEqual(result[0]["action"], "manual")
        self.assertEqual(result[0]["warning_code"], "dependencies.non_git_install")

    def test_plan_blocks_existing_target_owned_by_another_git_repository(self):
        dependency = {"name": "pack", "source_url": SOURCE, "commit": COMMIT_A, "manual": True}
        with tempfile.TemporaryDirectory() as directory:
            custom_nodes = Path(directory) / "custom_nodes"
            target = custom_nodes / "pack"
            target.mkdir(parents=True)
            repository = GitRepository("pack", target, "https://github.com/example/other-pack", COMMIT_B, False)
            with (
                patch.object(manager_module, "_scan_repositories", AsyncMock(return_value=[repository])),
                patch.object(manager_module, "_custom_node_roots", return_value=[custom_nodes]),
            ):
                result = self._run_plan([dependency])
        self.assertEqual(result[0]["action"], "manual")
        self.assertEqual(result[0]["warning_code"], "dependencies.target_exists")
        self.assertEqual(result[0]["warning_params"], {"path": "pack"})

    def test_plan_blocks_different_sources_with_same_target_name(self):
        dependencies = [
            {"name": "first", "source_url": "https://github.com/first/shared", "commit": COMMIT_A, "manual": True},
            {"name": "second", "source_url": "https://github.com/second/shared", "commit": COMMIT_B, "manual": True},
        ]
        with tempfile.TemporaryDirectory() as directory:
            custom_nodes = Path(directory) / "custom_nodes"
            with (
                patch.object(manager_module, "_scan_repositories", AsyncMock(return_value=[])),
                patch.object(manager_module, "_custom_node_roots", return_value=[custom_nodes]),
            ):
                result = self._run_plan(dependencies)
        self.assertTrue(all(item["action"] == "manual" for item in result))
        self.assertTrue(all(item["warning_code"] == "dependencies.target_exists" for item in result))
        self.assertTrue(all(item["warning_params"] == {"path": "shared"} for item in result))

    async def test_execute_reports_non_git_install_created_after_plan(self):
        item = {"name": "pack", "source_url": SOURCE, "requested": COMMIT_A, "action": "install"}
        with tempfile.TemporaryDirectory() as directory:
            custom_nodes = Path(directory) / "custom_nodes"
            marker = custom_nodes / "pack" / ".git" / ".cnr-id"
            marker.parent.mkdir(parents=True)
            marker.write_text("pack", encoding="utf-8")
            with (
                patch.object(manager_module, "_custom_node_roots", return_value=[custom_nodes]),
                patch.object(manager_module, "_inspect_repository", AsyncMock(return_value=None)),
            ):
                result, path = await GitAdapter()._execute_git_one(item, [])
        self.assertIsNone(path)
        self.assertEqual(result["state"], "failed")
        self.assertEqual(result["error_code"], "dependencies.non_git_install")

    async def test_execute_reports_different_git_repository_created_after_plan(self):
        item = {"name": "pack", "source_url": SOURCE, "requested": COMMIT_A, "action": "install"}
        with tempfile.TemporaryDirectory() as directory:
            custom_nodes = Path(directory) / "custom_nodes"
            target = custom_nodes / "pack"
            target.mkdir(parents=True)
            repository = GitRepository("pack", target, "https://github.com/example/other-pack", COMMIT_B, False)
            with (
                patch.object(manager_module, "_custom_node_roots", return_value=[custom_nodes]),
                patch.object(manager_module, "_inspect_repository", AsyncMock(return_value=repository)),
            ):
                result, path = await GitAdapter()._execute_git_one(item, [])
        self.assertIsNone(path)
        self.assertEqual(result["state"], "failed")
        self.assertEqual(result["error_code"], "dependencies.target_exists")
        self.assertEqual(result["error_params"], {"path": "pack"})

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

    async def test_remote_refresh_clears_stale_unpushed_detection(self):
        with tempfile.TemporaryDirectory() as directory:
            repository, origin, base = await self._create_repository(Path(directory))
            (repository / "plugin.py").write_text("second\n", encoding="utf-8")
            await manager_module._run_git("add", "plugin.py", cwd=repository)
            await manager_module._run_git("commit", "-m", "second", cwd=repository)
            second = await manager_module._run_git("rev-parse", "HEAD", cwd=repository)
            await manager_module._run_git("push", "origin", "main", cwd=repository)
            await manager_module._run_git("update-ref", "refs/remotes/origin/main", base, cwd=repository)
            before = await manager_module._run_git("rev-list", "HEAD", "--not", "--remotes", cwd=repository)
            self.assertIn(second, before)

            unpushed = await manager_module._refresh_remote_refs(repository, str(origin), None)

            self.assertEqual(unpushed, "")
            self.assertEqual(await manager_module._run_git("rev-parse", "refs/remotes/origin/main", cwd=repository), second)

    async def test_true_local_commits_are_backed_up_before_returning_to_tracked_branch(self):
        with tempfile.TemporaryDirectory() as directory:
            repository, origin, base = await self._create_repository(Path(directory))
            (repository / "plugin.py").write_text("local only\n", encoding="utf-8")
            await manager_module._run_git("add", "plugin.py", cwd=repository)
            await manager_module._run_git("commit", "-m", "local only", cwd=repository)
            local_commit = await manager_module._run_git("rev-parse", "HEAD", cwd=repository)

            unpushed = await manager_module._refresh_remote_refs(repository, str(origin), None)
            backup_ref = await manager_module._backup_unpushed_head(repository, None)
            await manager_module._checkout_pinned(repository, base, None)

            self.assertIn(local_commit, unpushed)
            self.assertEqual(await manager_module._run_git("rev-parse", backup_ref, cwd=repository), local_commit)
            self.assertEqual(await manager_module._run_git("branch", "--show-current", cwd=repository), "main")
            self.assertEqual(await manager_module._run_git("rev-parse", "--abbrev-ref", "@{upstream}", cwd=repository), "origin/main")
            self.assertEqual(await manager_module._run_git("status", "--porcelain", cwd=repository), "")

    async def test_execute_preserves_dirty_worktree_and_remains_launcher_updateable(self):
        with tempfile.TemporaryDirectory() as directory:
            custom_nodes = Path(directory) / "custom_nodes"
            repository, _origin, base = await self._create_repository(custom_nodes, "pack")
            (repository / "plugin.py").write_text("published update\n", encoding="utf-8")
            await manager_module._run_git("add", "plugin.py", cwd=repository)
            await manager_module._run_git("commit", "-m", "published update", cwd=repository)
            published = await manager_module._run_git("rev-parse", "HEAD", cwd=repository)
            await manager_module._run_git("push", "origin", "main", cwd=repository)
            (repository / "plugin.py").write_text("subscriber edit\n", encoding="utf-8")
            (repository / "subscriber.txt").write_text("subscriber file\n", encoding="utf-8")
            installed = GitRepository("pack", repository, SOURCE, published, True)
            item = {"name": "pack", "source_url": SOURCE, "requested": base, "action": "upgrade"}
            with (
                patch.object(manager_module, "_custom_node_roots", return_value=[custom_nodes]),
                patch.object(manager_module, "_refresh_remote_refs", AsyncMock(return_value="")),
            ):
                result, path = await GitAdapter()._execute_git_one(item, [installed])

            self.assertEqual(path, repository)
            self.assertEqual(result["state"], "success")
            self.assertEqual(len(result["backup_refs"]), 1)
            backup_ref = result["backup_refs"][0]
            self.assertTrue(backup_ref.startswith("refs/workflow-hub/backups/workflow-hub-worktree-"))
            self.assertEqual(await manager_module._run_git("status", "--porcelain", cwd=repository), "")
            self.assertEqual(await manager_module._run_git("rev-parse", "HEAD", cwd=repository), base)
            self.assertEqual(await manager_module._run_git("branch", "--show-current", cwd=repository), "main")
            self.assertEqual(await manager_module._run_git("rev-parse", "--abbrev-ref", "@{upstream}", cwd=repository), "origin/main")

            await manager_module._run_git("merge", "--ff-only", "origin/main", cwd=repository)
            self.assertEqual(await manager_module._run_git("rev-parse", "HEAD", cwd=repository), published)
            await manager_module._run_git("stash", "apply", "--index", backup_ref, cwd=repository)
            self.assertEqual((repository / "plugin.py").read_text(encoding="utf-8"), "subscriber edit\n")
            self.assertEqual((repository / "subscriber.txt").read_text(encoding="utf-8"), "subscriber file\n")

    async def test_failed_alignment_restores_dirty_worktree(self):
        with tempfile.TemporaryDirectory() as directory:
            custom_nodes = Path(directory) / "custom_nodes"
            repository, _origin, base = await self._create_repository(custom_nodes, "pack")
            (repository / "plugin.py").write_text("subscriber edit\n", encoding="utf-8")
            (repository / "subscriber.txt").write_text("subscriber file\n", encoding="utf-8")
            installed = GitRepository("pack", repository, SOURCE, base, True)
            item = {"name": "pack", "source_url": SOURCE, "requested": COMMIT_A, "action": "upgrade"}
            with (
                patch.object(manager_module, "_custom_node_roots", return_value=[custom_nodes]),
                patch.object(manager_module, "_refresh_remote_refs", AsyncMock(side_effect=manager_module.GitCommandError("fetch failed"))),
            ):
                result, path = await GitAdapter()._execute_git_one(item, [installed])

            self.assertIsNone(path)
            self.assertEqual(result["state"], "failed")
            self.assertEqual(result["error_code"], "dependencies.git_command_failed")
            self.assertEqual((repository / "plugin.py").read_text(encoding="utf-8"), "subscriber edit\n")
            self.assertEqual((repository / "subscriber.txt").read_text(encoding="utf-8"), "subscriber file\n")
            self.assertNotEqual(await manager_module._run_git("status", "--porcelain", cwd=repository), "")
            self.assertEqual(await manager_module._run_git("rev-parse", "HEAD", cwd=repository), base)
            self.assertEqual(await manager_module._run_git("branch", "--show-current", cwd=repository), "main")

    async def test_execute_preserves_local_only_head_and_returns_backup_reference(self):
        with tempfile.TemporaryDirectory() as directory:
            custom_nodes = Path(directory) / "custom_nodes"
            repository, _origin, base = await self._create_repository(custom_nodes, "pack")
            (repository / "plugin.py").write_text("local only\n", encoding="utf-8")
            await manager_module._run_git("add", "plugin.py", cwd=repository)
            await manager_module._run_git("commit", "-m", "local only", cwd=repository)
            local_commit = await manager_module._run_git("rev-parse", "HEAD", cwd=repository)
            installed = GitRepository("pack", repository, SOURCE, local_commit, False)
            item = {"name": "pack", "source_url": SOURCE, "requested": base, "action": "upgrade"}
            with (
                patch.object(manager_module, "_custom_node_roots", return_value=[custom_nodes]),
                patch.object(manager_module, "_refresh_remote_refs", AsyncMock(return_value=local_commit)),
            ):
                result, path = await GitAdapter()._execute_git_one(item, [installed])

            self.assertEqual(path, repository)
            self.assertEqual(result["state"], "success")
            self.assertTrue(str(result["backup_ref"]).startswith("workflow-hub-backup/"))
            self.assertEqual(await manager_module._run_git("rev-parse", result["backup_ref"], cwd=repository), local_commit)
            self.assertEqual(await manager_module._run_git("rev-parse", "HEAD", cwd=repository), base)
            self.assertEqual(await manager_module._run_git("branch", "--show-current", cwd=repository), "main")
            self.assertEqual(await manager_module._run_git("rev-parse", "--abbrev-ref", "@{upstream}", cwd=repository), "origin/main")

    async def test_requirement_generated_changes_are_preserved_and_worktree_is_left_clean(self):
        with tempfile.TemporaryDirectory() as directory:
            custom_nodes = Path(directory) / "custom_nodes"
            repository, _origin, base = await self._create_repository(custom_nodes, "pack")
            installed = GitRepository("pack", repository, SOURCE, base, False)
            action = {"name": "pack", "source_url": SOURCE, "requested": base, "action": "upgrade"}

            async def install_requirements(path, on_log=None):
                (path / "plugin.py").write_text("generated tracked change\n", encoding="utf-8")
                (path / "generated.txt").write_text("generated file\n", encoding="utf-8")
                return True

            with (
                patch.object(manager_module, "_custom_node_roots", return_value=[custom_nodes]),
                patch.object(manager_module, "_scan_repositories", AsyncMock(return_value=[installed])),
                patch.object(manager_module, "_refresh_remote_refs", AsyncMock(return_value="")),
                patch.object(manager_module, "_install_python_requirements", install_requirements),
            ):
                result = await GitAdapter().execute([action])

            self.assertEqual(result[0]["state"], "success")
            self.assertEqual(result[0]["python_requirements"], "installed")
            self.assertEqual(len(result[0]["backup_refs"]), 1)
            backup_ref = result[0]["backup_refs"][0]
            self.assertIn("workflow-hub-requirements-", backup_ref)
            self.assertEqual(await manager_module._run_git("status", "--porcelain", cwd=repository), "")
            self.assertEqual((repository / "plugin.py").read_text(encoding="utf-8"), "base\n")
            self.assertFalse((repository / "generated.txt").exists())
            await manager_module._run_git("stash", "apply", "--index", backup_ref, cwd=repository)
            self.assertEqual((repository / "plugin.py").read_text(encoding="utf-8"), "generated tracked change\n")
            self.assertEqual((repository / "generated.txt").read_text(encoding="utf-8"), "generated file\n")

    async def test_git_dependencies_run_serially_through_requirements(self):
        events: list[str] = []
        actions = [
            {"name": "one", "source_url": "https://github.com/example/one", "requested": COMMIT_A, "action": "install"},
            {"name": "two", "source_url": "https://github.com/example/two", "requested": COMMIT_B, "action": "install"},
        ]

        async def execute_one(item, _repositories, on_log=None):
            events.append(f"git:{item['name']}")
            return {
                **item,
                "installer": "git",
                "state": "success",
                "error_code": None,
                "error_params": {},
                "_cloned": True,
            }, Path(item["name"])

        async def install_requirements(path, on_log=None):
            events.append(f"requirements:{path.name}")
            return False

        adapter = GitAdapter()
        with (
            patch.object(manager_module, "_scan_repositories", AsyncMock(return_value=[])),
            patch.object(adapter, "_execute_git_one", execute_one),
            patch.object(manager_module, "_install_python_requirements", install_requirements),
            patch.object(manager_module, "_stash_worktree_changes", AsyncMock(return_value=None)),
        ):
            result = await adapter.execute(actions)
        self.assertEqual(events, ["git:one", "requirements:one", "git:two", "requirements:two"])
        self.assertTrue(all(item["state"] == "success" for item in result))

    async def _create_repository(self, root: Path, name: str = "work") -> tuple[Path, Path, str]:
        root.mkdir(parents=True, exist_ok=True)
        repository = root / name
        origin = root / "origin.git"
        await manager_module._run_git("init", str(repository))
        await manager_module._run_git("init", "--bare", str(origin))
        await manager_module._run_git("config", "user.email", "workflow-hub@example.invalid", cwd=repository)
        await manager_module._run_git("config", "user.name", "Workflow Hub Tests", cwd=repository)
        (repository / "plugin.py").write_text("base\n", encoding="utf-8")
        await manager_module._run_git("add", "plugin.py", cwd=repository)
        await manager_module._run_git("commit", "-m", "base", cwd=repository)
        await manager_module._run_git("branch", "-M", "main", cwd=repository)
        await manager_module._run_git("remote", "add", "origin", str(origin), cwd=repository)
        await manager_module._run_git("push", "-u", "origin", "main", cwd=repository)
        return repository, origin, await manager_module._run_git("rev-parse", "HEAD", cwd=repository)

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
