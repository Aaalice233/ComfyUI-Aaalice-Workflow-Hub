import unittest

from workflow_hub.assets import _image_references


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
