import asyncio
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from workflow_hub.storage import UserStorage
from workflow_hub.service import aggregate_catalog


class StorageTests(unittest.IsolatedAsyncioTestCase):
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
