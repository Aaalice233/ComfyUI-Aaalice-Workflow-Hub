from __future__ import annotations

import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from workflow_hub.compatibility import current_comfyui_version, stamp_product_comfyui_version


class CompatibilityTests(unittest.TestCase):
    def test_detects_comfyui_core_version(self) -> None:
        with patch.dict(sys.modules, {"comfyui_version": SimpleNamespace(__version__="0.28.3")}):
            self.assertEqual(current_comfyui_version(), "0.28.3")

    def test_stamps_all_published_versions_with_detected_core(self) -> None:
        product = {
            "versions": [
                {"version": "1.0", "comfyui": {"minimum": "0.20.0", "maximum": None}},
            ]
        }

        stamped = stamp_product_comfyui_version(product, "0.28.3")

        self.assertEqual(stamped["versions"][0]["comfyui"], {"minimum": "0.28.3", "maximum": "0.28.3"})
        self.assertEqual(product["versions"][0]["comfyui"], {"minimum": "0.20.0", "maximum": None})


if __name__ == "__main__":
    unittest.main()
