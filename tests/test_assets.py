import unittest

from workflow_hub.assets import _image_references
from workflow_hub.packages import _replace_load_image_references


class AssetTests(unittest.TestCase):
    def test_image_references_include_subgraphs_and_image_widgets(self):
        workflow = {
            "nodes": [
                {"id": 1, "type": "LoadImage", "widgets_values": ["root.png"]},
                {
                    "id": 2,
                    "type": "CustomImageNode",
                    "inputs": [{"name": "image", "widget": {"name": "image"}}],
                    "widgets_values": ["sidebar.jpg"],
                },
            ],
            "definitions": {
                "subgraphs": [
                    {"nodes": [{"id": 3, "type": "LoadImageMask", "widgets_values": ["nested.webp", "alpha"]}]}
                ]
            },
        }
        references = _image_references(workflow)
        self.assertEqual(set(references), {"root.png", "sidebar.jpg", "nested.webp"})
        self.assertEqual(references["nested.webp"], {"3"})

    def test_package_rewrites_nested_and_image_widget_references(self):
        workflow = {
            "nodes": [
                {"id": 1, "type": "LoadImage", "widgets_values": ["root.png"]},
                {
                    "id": 2,
                    "type": "CustomImageNode",
                    "inputs": [{"name": "image", "widget": {"name": "image"}}],
                    "widgets_values": ["sidebar.jpg"],
                },
            ],
            "definitions": {
                "subgraphs": [
                    {"nodes": [{"id": 3, "type": "LoadImageMask", "widgets_values": ["nested.webp", "alpha"]}]}
                ]
            },
        }
        _replace_load_image_references(
            workflow,
            {"root.png": "inputs/root.png", "sidebar.jpg": "inputs/sidebar.jpg", "nested.webp": "inputs/nested.webp"},
        )
        self.assertEqual(workflow["nodes"][0]["widgets_values"][0], "inputs/root.png")
        self.assertEqual(workflow["nodes"][1]["widgets_values"][0], "inputs/sidebar.jpg")
        self.assertEqual(workflow["definitions"]["subgraphs"][0]["nodes"][0]["widgets_values"][0], "inputs/nested.webp")
