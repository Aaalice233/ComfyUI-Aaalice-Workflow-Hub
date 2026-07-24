import unittest

from workflow_hub.assets import clear_lora_manager


class AssetTests(unittest.TestCase):
    def test_clear_lora_manager_only_changes_recognized_nodes(self):
        workflow = {
            "nodes": [
                {
                    "id": 1,
                    "type": "Lora Loader (LoraManager)",
                    "widgets_values": [
                        {"version": 1, "textWidgetName": "text"},
                        "<lora:daily/style:0.7> portrait",
                        [{"name": "daily/style", "strength": 0.7, "active": True}],
                    ],
                },
                {"id": 2, "type": "Text", "widgets_values": ["<lora:keep:1>"]},
            ]
        }
        cleaned = clear_lora_manager(workflow)
        self.assertEqual(cleaned["nodes"][0]["widgets_values"][1], "portrait")
        self.assertEqual(cleaned["nodes"][0]["widgets_values"][2], [])
        self.assertEqual(cleaned["nodes"][1]["widgets_values"][0], "<lora:keep:1>")
        self.assertIn("<lora:daily/style:0.7>", workflow["nodes"][0]["widgets_values"][1])
