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

    async def test_monitor_persists_state_changes_and_final_result(self):
        with tempfile.TemporaryDirectory() as directory:
            storage = UserStorage(Path(directory))
            store = OperationStore()
            operation = await store.create("download", storage)
            persisted = 0

            async def counting_persist(item):
                nonlocal persisted
                persisted += 1
                await OperationStore.persist(store, item)

            store.persist = counting_persist  # type: ignore[method-assign]
            await asyncio.sleep(0.6)
            idle_writes = persisted
            operation.stage = "downloading"
            operation.logs.append("started")
            await asyncio.sleep(0.6)
            self.assertGreater(persisted, idle_writes)
            operation.status = "success"
            operation.stage = "complete"
            await asyncio.sleep(0.6)

            restored = OperationStore()
            items = await restored.list(storage)
            self.assertEqual(items[0]["status"], "success")
            self.assertEqual(items[0]["logs"], ["started"])

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

    async def test_completed_operations_can_be_deleted_and_persisted(self):
        with tempfile.TemporaryDirectory() as directory:
            storage = UserStorage(Path(directory))
            store = OperationStore()
            operation = await store.create("download", storage)
            operation.status = "success"
            operation.stage = "complete"
            await store.persist(operation)

            self.assertEqual(await store.delete(operation.id, storage), "deleted")
            self.assertEqual(await store.list(storage), [])
            await asyncio.sleep(0.6)

    async def test_bulk_delete_keeps_running_and_late_manager_operations(self):
        with tempfile.TemporaryDirectory() as directory:
            storage = UserStorage(Path(directory))
            store = OperationStore()
            success = await store.create("download", storage)
            failed = await store.create("publish", storage)
            active = await store.create("dependencies", storage)
            success.status = "success"
            success.stage = "complete"
            failed.status = "failed"
            failed.stage = "failed"
            failed.error_code = "operation.failed"
            late_manager = await store.create("dependencies", storage)
            late_manager.status = "failed"
            late_manager.stage = "failed"
            late_manager.error_code = "dependencies.manager_result_unknown"
            for operation in (success, failed, active, late_manager):
                await store.persist(operation)

            self.assertEqual(await store.delete(active.id, storage), "active")
            deleted = await store.delete_completed(storage)
            self.assertEqual(set(deleted), {success.id, failed.id})
            self.assertEqual({item["id"] for item in await store.list(storage)}, {active.id, late_manager.id})

            active.status = "failed"
            active.stage = "failed"
            await store.persist(active)
            restored = OperationStore()
            self.assertEqual(
                {item["id"] for item in await restored.list(storage)},
                {active.id, late_manager.id},
            )
            late_manager.status = "failed"
            late_manager.error_code = "operation.failed"
            await store.persist(late_manager)
            await asyncio.sleep(0.6)

    async def test_corrupt_operation_state_is_quarantined(self):
        with tempfile.TemporaryDirectory() as directory:
            storage = UserStorage(Path(directory))
            state = storage.state_dir / "operations.json"
            state.write_text("{", encoding="utf-8")

            restored = OperationStore()
            self.assertEqual(await restored.list(storage), [])
            self.assertEqual(state.read_text(encoding="utf-8").strip(), "[]")
            self.assertEqual(len(list(storage.state_dir.glob("operations.corrupt-*.json"))), 1)

    async def test_public_operation_redacts_sensitive_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            storage = UserStorage(Path(directory))
            store = OperationStore()
            operation = await store.create(
                "download",
                storage,
                {"access_token": "secret", "nested": {"password": "pw"}, "url": "https://example.test"},
            )

            public = operation.public()
            self.assertEqual(public["metadata"]["access_token"], "[REDACTED]")
            self.assertEqual(public["metadata"]["nested"]["password"], "[REDACTED]")
            self.assertEqual(public["metadata"]["url"], "https://example.test")
