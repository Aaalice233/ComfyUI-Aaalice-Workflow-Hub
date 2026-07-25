import unittest
from unittest.mock import AsyncMock, patch

from workflow_hub.manager import ManagerAdapter, resolve_workflow_dependencies


class ManagerDependencyResolutionTests(unittest.TestCase):
    def test_object_info_maps_node_type_to_installed_manager_plugin(self):
        dependencies, mode, unresolved = resolve_workflow_dependencies(
            {"Text (LoraManager)"},
            {},
            {"Text (LoraManager)": {"python_module": "custom_nodes.comfyui-lora-manager"}},
            {
                "comfyui-lora-manager": {
                    "key": "comfyui-lora-manager",
                    "registry_id": "comfyui-lora-manager",
                    "aux_id": "AIGODLIKE/ComfyUI-Lora-Manager",
                    "name": "comfyui-lora-manager",
                    "version": "1.1.6",
                    "enabled": True,
                }
            },
        )

        self.assertEqual(mode, "workflow")
        self.assertEqual(unresolved, [])
        self.assertEqual(dependencies[0]["registry_id"], "comfyui-lora-manager")
        self.assertEqual(dependencies[0]["version"], "1.1.6")

    def test_unresolved_node_falls_back_to_enabled_manager_plugins(self):
        dependencies, mode, unresolved = resolve_workflow_dependencies(
            {"lth_extended_prompting_nodes"},
            {},
            {},
            {
                "pack-a": {
                    "key": "pack-a",
                    "registry_id": "pack-a",
                    "name": "Pack A",
                    "version": "1.0.0",
                    "enabled": True,
                },
                "pack-b": {
                    "key": "pack-b",
                    "registry_id": "pack-b",
                    "name": "Pack B",
                    "version": "2.0.0",
                    "enabled": False,
                },
            },
        )

        self.assertEqual(mode, "installed_fallback")
        self.assertEqual(unresolved, ["lth_extended_prompting_nodes"])
        self.assertEqual([item["name"] for item in dependencies], ["Pack A"])
        self.assertNotIn("lth_extended_prompting_nodes", [item["name"] for item in dependencies])

    def test_git_clone_with_registry_id_uses_manager_installable_dependency(self):
        dependencies, mode, unresolved = resolve_workflow_dependencies(
            {"DevNode"},
            {"comfyui-dev-pack": [["DevNode"], {}]},
            {},
            {
                "comfyui-dev-pack": {
                    "key": "comfyui-dev-pack",
                    "registry_id": "comfyui-dev-pack",
                    "aux_id": "owner/ComfyUI-Dev-Pack",
                    "name": "ComfyUI-Dev-Pack",
                    "version": "abcdef1234567890",
                    "enabled": True,
                }
            },
        )

        self.assertEqual((mode, unresolved), ("workflow", []))
        self.assertEqual(dependencies[0]["registry_id"], "comfyui-dev-pack")
        self.assertIsNone(dependencies[0]["version"])
        self.assertFalse(dependencies[0]["manual"])
        self.assertTrue(dependencies[0]["development"])
        self.assertEqual(dependencies[0]["installed_version"], "abcdef1234567890")

    def test_git_clone_without_registry_id_stays_manual_github_dependency(self):
        dependencies, mode, unresolved = resolve_workflow_dependencies(
            {"DevNode"},
            {"owner/ComfyUI-Dev-Pack": [["DevNode"], {}]},
            {},
            {
                "github:owner/ComfyUI-Dev-Pack": {
                    "key": "github:owner/ComfyUI-Dev-Pack",
                    "registry_id": None,
                    "aux_id": "owner/ComfyUI-Dev-Pack",
                    "name": "ComfyUI-Dev-Pack",
                    "version": "abcdef1234567890",
                    "enabled": True,
                }
            },
        )

        self.assertEqual((mode, unresolved), ("workflow", []))
        self.assertIsNone(dependencies[0]["registry_id"])
        self.assertTrue(dependencies[0]["manual"])
        self.assertEqual(dependencies[0]["source_url"], "https://github.com/owner/ComfyUI-Dev-Pack")


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
