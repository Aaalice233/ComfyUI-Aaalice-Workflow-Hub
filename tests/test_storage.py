import asyncio
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock, patch

from workflow_hub.storage import UserStorage
from workflow_hub.service import aggregate_catalog, catalog_snapshot


class StorageTests(unittest.IsolatedAsyncioTestCase):
    async def test_workflows_root_is_the_current_user_workflows_directory(self):
        with TemporaryDirectory() as folder:
            storage = UserStorage(Path(folder))
            self.assertEqual(storage.workflows_root, Path(folder).resolve() / "workflows")

    async def test_atomic_update_and_user_isolation(self):
        with TemporaryDirectory() as folder:
            first = UserStorage(Path(folder) / "one")
            second = UserStorage(Path(folder) / "two")

            async def increment():
                await first.update_json("counter.json", {"value": 0}, lambda item: {"value": item["value"] + 1})

            await asyncio.gather(*(increment() for _ in range(20)))
            self.assertEqual((await first.read_json("counter.json", {}))["value"], 20)
            await second.write_json("counter.json", {"value": 99})
            self.assertEqual((await first.read_json("counter.json", {}))["value"], 20)
            self.assertEqual(json.loads((second.state_dir / "counter.json").read_text(encoding="utf-8"))["value"], 99)

    async def test_catalog_snapshot_reads_subscriptions_once(self):
        with TemporaryDirectory() as folder:
            storage = UserStorage(Path(folder))
            with patch("workflow_hub.service.list_subscriptions", new=AsyncMock(return_value=[])) as subscriptions:
                snapshot = await catalog_snapshot(storage)
            self.assertEqual(snapshot, {"sources": [], "products": []})
            subscriptions.assert_awaited_once_with(storage)

    async def test_missing_download_is_removed_from_installed_state(self):
        with TemporaryDirectory() as folder:
            storage = UserStorage(Path(folder))
            existing = storage.workflows_root / "existing.json"
            existing.write_text("{}", encoding="utf-8")
            await storage.write_json(
                "installed.json",
                [
                    {"owner": "owner", "repo": "repo", "workflow_id": "one", "version": "1.0", "path": str(existing)},
                    {"owner": "owner", "repo": "repo", "workflow_id": "two", "version": "1.0", "path": str(storage.workflows_root / "missing.json")},
                ],
            )

            await aggregate_catalog(storage)

            installed = await storage.read_json("installed.json", [])
            self.assertEqual([item["workflow_id"] for item in installed], ["one"])


class FromRequestTests(unittest.TestCase):
    def _fake_server(self, manager):
        import sys
        from unittest import mock

        server = mock.ModuleType("server")
        server.PromptServer = type("PromptServer", (), {"instance": type("Inst", (), {"user_manager": manager})()})
        return mock.patch.dict(sys.modules, {"server": server})

    def test_unknown_user_falls_back_to_default_directory(self):
        with TemporaryDirectory() as folder:
            manager = type("Manager", (), {"get_request_user_filepath": lambda *args, **kwargs: (_ for _ in ()).throw(KeyError("Unknown user: default"))})()
            folder_paths = type("FolderPaths", (), {"get_user_directory": staticmethod(lambda: folder)})()
            import sys
            from unittest import mock

            with self._fake_server(manager), mock.patch.dict(sys.modules, {"folder_paths": folder_paths}):
                storage = UserStorage.from_request(object())
            self.assertEqual(storage.root, (Path(folder) / "default").resolve())

    def test_known_user_uses_manager_path(self):
        with TemporaryDirectory() as folder:
            target = Path(folder) / "alice" / "workflow_hub" / ".root"
            manager = type("Manager", (), {"get_request_user_filepath": lambda *args, **kwargs: str(target)})()
            with self._fake_server(manager):
                storage = UserStorage.from_request(object())
            self.assertEqual(storage.root, (Path(folder) / "alice").resolve())
