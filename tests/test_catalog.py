import json
import unittest
from pathlib import Path

from pydantic import ValidationError

from workflow_hub.catalog import Catalog, normalize_version

ROOT = Path(__file__).resolve().parents[1]


class CatalogTests(unittest.TestCase):
    def test_short_version_is_normalized_for_comparison(self):
        self.assertEqual(normalize_version("1.12"), (1, 12, 0))
        self.assertEqual(normalize_version("1.12.3"), (1, 12, 3))

    def test_valid_example(self):
        catalog = Catalog.model_validate_json((ROOT / "examples/valid/workflow-catalog.json").read_bytes())
        self.assertEqual(catalog.workflows[0].versions[0].version, "1.12")

    def test_duplicate_normalized_version_is_rejected(self):
        with self.assertRaises(ValidationError):
            Catalog.model_validate_json((ROOT / "examples/invalid/duplicate-normalized-version.json").read_bytes())

    def test_schema_is_valid_json(self):
        schema = json.loads((ROOT / "schemas/workflow-catalog.schema.json").read_text(encoding="utf-8"))
        self.assertEqual(schema["$schema"], "https://json-schema.org/draft/2020-12/schema")
