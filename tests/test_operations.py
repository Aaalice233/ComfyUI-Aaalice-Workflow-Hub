import asyncio
import tempfile
import uuid
from pathlib import Path
from unittest import IsolatedAsyncioTestCase

from workflow_hub.operations import OperationStore
from workflow_hub.storage import UserStorage


class OperationStoreTests(IsolatedAsyncioTestCase):
    async def test_operations_survive_restart_and_are_user_isolated(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = UserStorage(root / "first")
            second = UserStorage(root / "second")
            store = OperationStore()
            operation = await store.create("dependencies", first, {"workflow_key": "demo"})
            operation.status = "success"
            operation.stage = "complete"
            operation.logs.append("completed")
            await store.persist(operation)
            await asyncio.sleep(0.6)

            restored = OperationStore()
            items = await restored.list(first)
            self.assertEqual(len(items), 1)
            self.assertEqual(items[0]["id"], operation.id)
            self.assertEqual(items[0]["status"], "success")
            self.assertEqual(items[0]["metadata"]["workflow_key"], "demo")
            self.assertEqual(await restored.list(second), [])

    async def test_running_operation_is_marked_interrupted_after_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            storage = UserStorage(Path(directory))
            await storage.write_json("operations.json", [{
                "id": uuid.uuid4().hex,
                "kind": "download",
                "stage": "downloading",
                "status": "running",
                "logs": [],
                "created_at": "2026-01-01T00:00:00+00:00",
            }])

            restored = OperationStore()
            items = await restored.list(storage)
            self.assertEqual(items[0]["status"], "failed")
            self.assertEqual(items[0]["stage"], "failed")
            self.assertEqual(items[0]["error_code"], "operation.interrupted")
