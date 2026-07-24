import unittest
from unittest.mock import AsyncMock, patch

from workflow_hub.manager import ManagerAdapter


class ManagerPlanTests(unittest.IsolatedAsyncioTestCase):
    async def test_plan_has_safe_newer_and_manual_states(self):
        adapter = ManagerAdapter("http://127.0.0.1:8188")
        with patch.object(adapter, "installed", AsyncMock(return_value={"pack": {"version": "2.0.0"}})):
            result = await adapter.plan([
                {"registry_id": "pack", "name": "Pack", "version": "1.0.0", "required": True, "manual": False},
                {"registry_id": None, "name": "Unknown", "required": True, "manual": True},
            ])
        self.assertEqual(result[0]["action"], "newer")
        self.assertEqual(result[1]["action"], "manual")

    async def test_conflicting_workflow_versions_are_never_automatic(self):
        adapter = ManagerAdapter("http://127.0.0.1:8188")
        with patch.object(adapter, "installed", AsyncMock(return_value={})):
            result = await adapter.plan([
                {"registry_id": "pack", "name": "Pack", "version": "1.0.0", "required": True, "manual": False},
                {"registry_id": "pack", "name": "Pack", "version": "2.0.0", "required": True, "manual": False},
            ])
        self.assertEqual([item["action"] for item in result], ["conflict", "conflict"])
