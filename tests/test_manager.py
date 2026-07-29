import sys
import types
import unittest
from unittest.mock import AsyncMock, patch

from workflow_hub import manager as manager_module
from workflow_hub.manager import ManagerAdapter, local_manager_status, resolve_workflow_dependencies


class FakeResponse:
    def __init__(self, status, text="", payload=None):
        self.status = status
        self._text = text
        self._payload = payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def text(self):
        return self._text

    async def json(self):
        return self._payload


class FakeSession:
    def __init__(self, responses, record):
        self._responses = responses
        self._record = record

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    def get(self, url, **kwargs):
        return self._respond("GET", url, None)

    def post(self, url, json=None, **kwargs):
        return self._respond("POST", url, json)

    def _respond(self, method, url, payload):
        self._record.append((method, url, payload))
        key = (method, url)
        if key not in self._responses:
            raise AssertionError(f"unexpected request: {method} {url}")
        return self._responses[key]


def fake_session_factory(responses, record):
    return lambda *args, **kwargs: FakeSession(responses, record)


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


class ManagerVersionGateTests(unittest.TestCase):
    def test_legacy_3x_versions_are_compatible(self):
        self.assertTrue(manager_module._is_compatible_version((3, 0)))
        self.assertTrue(manager_module._is_compatible_version((3, 39)))

    def test_v2_requires_4_2_1(self):
        self.assertFalse(manager_module._is_compatible_version((4, 2, 0)))
        self.assertTrue(manager_module._is_compatible_version((4, 2, 1)))

    def test_local_status_falls_back_to_top_level_manager_core(self):
        fake = types.SimpleNamespace(version_str="V3.39")
        missing = {"comfyui_manager": None, "comfyui_manager.glob": None, "comfyui_manager.legacy": None}
        with patch.dict(sys.modules, missing):
            with patch.dict(sys.modules, {"manager_core": fake}):
                status = local_manager_status()
        self.assertTrue(status["available"])
        self.assertTrue(status["compatible"])
        self.assertEqual(status["version"], "V3.39")

    def test_local_status_unavailable_without_manager(self):
        missing = {
            "comfyui_manager": None,
            "comfyui_manager.glob": None,
            "comfyui_manager.legacy": None,
            "manager_core": None,
        }
        with patch.dict(sys.modules, missing):
            status = local_manager_status()
        self.assertFalse(status["available"])
        self.assertFalse(status["compatible"])


class ManagerLegacyApiTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        manager_module._flavor_cache.clear()

    async def test_status_falls_back_to_legacy_version_endpoint(self):
        origin = "http://127.0.0.1:8188"
        record = []
        responses = {
            ("GET", f"{origin}/v2/manager/version"): FakeResponse(404),
            ("GET", f"{origin}/manager/version"): FakeResponse(200, "V3.39"),
        }
        adapter = ManagerAdapter(origin)
        with patch.object(manager_module.aiohttp, "ClientSession", fake_session_factory(responses, record)):
            status = await adapter.status()
        self.assertTrue(status["available"])
        self.assertEqual(status["api"], "legacy")
        self.assertEqual(status["version"], "V3.39")

    async def test_installed_parses_legacy_node_pack_dict(self):
        origin = "http://127.0.0.1:8189"
        record = []
        responses = {
            ("GET", f"{origin}/v2/manager/version"): FakeResponse(404),
            ("GET", f"{origin}/manager/version"): FakeResponse(200, "V3.39"),
            ("GET", f"{origin}/customnode/installed"): FakeResponse(200, payload={
                "ComfyUI-Impact-Pack": {
                    "ver": "8.22",
                    "cnr_id": "comfyui-impact-pack",
                    "aux_id": "ltdrdata/ComfyUI-Impact-Pack",
                    "enabled": True,
                },
                "rgthree-comfy": {
                    "ver": "abcdef1",
                    "cnr_id": "",
                    "aux_id": "rgthree/rgthree-comfy",
                    "enabled": True,
                },
            }),
        }
        adapter = ManagerAdapter(origin)
        with patch.object(manager_module.aiohttp, "ClientSession", fake_session_factory(responses, record)):
            installed = await adapter.installed()
        registry_pack = installed["comfyui-impact-pack"]
        self.assertEqual(registry_pack["version"], "8.22")
        self.assertEqual(registry_pack["aux_id"], "ltdrdata/ComfyUI-Impact-Pack")
        git_pack = installed["github:rgthree/rgthree-comfy"]
        self.assertIsNone(git_pack["registry_id"])
        self.assertEqual(git_pack["version"], "abcdef1")

    async def test_execute_queues_legacy_installs_then_starts_queue(self):
        origin = "http://127.0.0.1:8190"
        record = []
        responses = {
            ("GET", f"{origin}/v2/manager/version"): FakeResponse(404),
            ("GET", f"{origin}/manager/version"): FakeResponse(200, "V3.39"),
            ("POST", f"{origin}/manager/queue/install"): FakeResponse(200),
            ("GET", f"{origin}/manager/queue/start"): FakeResponse(201),
        }
        adapter = ManagerAdapter(origin)
        actions = [{"action": "install", "registry_id": "pack-a", "name": "Pack A", "requested": "1.2.3"}]
        with patch.object(manager_module.aiohttp, "ClientSession", fake_session_factory(responses, record)):
            queued = await adapter.execute(actions, "workflow-hub")
        self.assertEqual(len(queued), 1)
        install_calls = [entry for entry in record if entry[0] == "POST" and entry[1].endswith("/manager/queue/install")]
        self.assertEqual(len(install_calls), 1)
        payload = install_calls[0][2]
        self.assertEqual(payload["id"], "pack-a")
        self.assertEqual(payload["version"], "1.2.3")
        self.assertEqual(payload["selected_version"], "1.2.3")
        self.assertEqual(payload["ui_id"], "pack-a")
        self.assertEqual(payload["channel"], "default")
        self.assertEqual(payload["mode"], "cache")
        self.assertFalse(payload["skip_post_install"])
        self.assertIn(("GET", f"{origin}/manager/queue/start", None), record)


    async def test_queue_status_normalizes_legacy_counts(self):
        origin = "http://127.0.0.1:8191"
        record = []
        responses = {
            ("GET", f"{origin}/v2/manager/version"): FakeResponse(404),
            ("GET", f"{origin}/manager/version"): FakeResponse(200, "V3.39"),
            ("GET", f"{origin}/manager/queue/status"): FakeResponse(200, payload={
                "total_count": 3, "done_count": 1, "in_progress_count": 1, "is_processing": True,
            }),
        }
        adapter = ManagerAdapter(origin)
        with patch.object(manager_module.aiohttp, "ClientSession", fake_session_factory(responses, record)):
            status = await adapter.queue_status("workflow-hub-x")
        self.assertEqual(status, {"api": "legacy", "total": 3, "done": 1, "in_progress": 1, "processing": True})
        # legacy 队列状态不支持 client_id 过滤，URL 不应带查询参数。
        self.assertIn(("GET", f"{origin}/manager/queue/status", None), record)

    async def test_queue_status_v2_sums_history_and_pending(self):
        origin = "http://127.0.0.1:8192"
        record = []
        responses = {
            ("GET", f"{origin}/v2/manager/version"): FakeResponse(200, '"4.2.2"'),
            ("GET", f"{origin}/v2/manager/queue/status?client_id=wf-1"): FakeResponse(200, payload={
                "client_id": "wf-1", "total_count": 2, "done_count": 1,
                "in_progress_count": 1, "pending_count": 1, "is_processing": True,
            }),
        }
        adapter = ManagerAdapter(origin)
        with patch.object(manager_module.aiohttp, "ClientSession", fake_session_factory(responses, record)):
            status = await adapter.queue_status("wf-1")
        self.assertEqual(status, {"api": "v2", "total": 3, "done": 1, "in_progress": 1, "processing": True})

    async def test_queue_history_v2_normalizes_task_results(self):
        origin = "http://127.0.0.1:8193"
        record = []
        responses = {
            ("GET", f"{origin}/v2/manager/version"): FakeResponse(200, '"4.2.2"'),
            ("GET", f"{origin}/v2/manager/queue/history?client_id=wf-1"): FakeResponse(200, payload={
                "history": {
                    "task-1": {
                        "ui_id": "pack-a", "client_id": "wf-1", "kind": "install",
                        "result": "success",
                        "status": {"status_str": "success", "completed": True, "messages": []},
                    },
                    "task-2": {
                        "ui_id": "pack-b", "client_id": "wf-1", "kind": "install",
                        "result": "pip install failed",
                        "status": {"status_str": "failed", "completed": True, "messages": []},
                    },
                }
            }),
        }
        adapter = ManagerAdapter(origin)
        with patch.object(manager_module.aiohttp, "ClientSession", fake_session_factory(responses, record)):
            history = await adapter.queue_history("wf-1")
        self.assertEqual(history["pack-a"], {"outcome": "success", "message": "success"})
        self.assertEqual(history["pack-b"], {"outcome": "failed", "message": "pip install failed"})

    async def test_queue_history_legacy_returns_empty(self):
        origin = "http://127.0.0.1:8194"
        record = []
        responses = {
            ("GET", f"{origin}/v2/manager/version"): FakeResponse(404),
            ("GET", f"{origin}/manager/version"): FakeResponse(200, "V3.39"),
        }
        adapter = ManagerAdapter(origin)
        with patch.object(manager_module.aiohttp, "ClientSession", fake_session_factory(responses, record)):
            history = await adapter.queue_history("wf-1")
        self.assertEqual(history, {})


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
