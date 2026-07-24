import asyncio
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from workflow_hub.storage import UserStorage


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
