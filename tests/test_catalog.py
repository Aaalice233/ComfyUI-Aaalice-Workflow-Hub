import json
import unittest
from pathlib import Path

from pydantic import ValidationError

from workflow_hub.catalog import Catalog, WorkflowProduct, merge_product, normalize_version, prepare_publish_product

ROOT = Path(__file__).resolve().parents[1]


class CatalogTests(unittest.TestCase):
    def test_short_version_is_normalized_for_comparison(self):
        self.assertEqual(normalize_version("1.12"), (1, 12, 0))
        self.assertEqual(normalize_version("1.12.3"), (1, 12, 3))

    def test_valid_example(self):
        catalog = Catalog.model_validate_json((ROOT / "examples/valid/workflow-catalog.json").read_bytes())
        self.assertEqual(catalog.workflows[0].versions[0].version, "1.12")
        self.assertEqual(catalog.workflows[0].category, "Portrait")
        self.assertIsNotNone(catalog.workflows[0].cover)
        self.assertEqual(catalog.workflows[0].versions[0].inputs[0].source, "portrait-reference.png")
        self.assertEqual(catalog.workflows[0].versions[0].models[1].type, "loras")

    def test_inputs_default_to_empty(self):
        payload = json.loads((ROOT / "examples/valid/workflow-catalog.json").read_text(encoding="utf-8"))
        payload["workflows"][0]["versions"][0].pop("inputs")
        catalog = Catalog.model_validate(payload)
        self.assertEqual(catalog.workflows[0].versions[0].inputs, [])

    def test_category_is_required(self):
        payload = json.loads((ROOT / "examples/valid/workflow-catalog.json").read_text(encoding="utf-8"))
        payload["workflows"][0].pop("category")
        with self.assertRaises(ValidationError):
            Catalog.model_validate(payload)

    def test_nested_category_path_is_rejected(self):
        payload = json.loads((ROOT / "examples/valid/workflow-catalog.json").read_text(encoding="utf-8"))
        payload["workflows"][0]["category"] = "Portrait/Studio"
        with self.assertRaises(ValidationError):
            Catalog.model_validate(payload)

    def test_new_version_inherits_existing_project_cover(self):
        catalog = Catalog.model_validate_json((ROOT / "examples/valid/workflow-catalog.json").read_bytes())
        existing = catalog.workflows[0]
        next_version = existing.versions[0].model_copy(
            update={
                "version": "1.13",
                "release_tag": f"{existing.id}-v1.13",
                "repository_path": f"{existing.repository_path}/versions/v1.13",
            }
        )
        incoming_payload = existing.model_dump(mode="json")
        incoming_payload["cover"] = None
        incoming_payload["versions"] = [next_version.model_dump(mode="json")]
        incoming = type(existing).model_validate(incoming_payload)
        merged = merge_product(catalog, incoming)
        self.assertEqual(merged.workflows[0].cover, existing.cover)
        self.assertEqual(merged.workflows[0].category, existing.category)

    def test_publish_paths_preserve_readable_chinese_names(self):
        prepared = prepare_publish_product(
            {
                "id": "test-workflow",
                "name": "测试工作流",
                "category": "测试系列",
                "versions": [{"version": "1.0"}],
            }
        )
        self.assertEqual(prepared["repository_path"], "workflows/测试系列/测试工作流")
        self.assertEqual(
            prepared["versions"][0]["repository_path"],
            "workflows/测试系列/测试工作流/versions/v1.0",
        )

    def test_repository_path_characters_are_rejected(self):
        payload = json.loads((ROOT / "examples/valid/workflow-catalog.json").read_text(encoding="utf-8"))
        payload["workflows"][0]["name"] = "Portrait:Basic"
        with self.assertRaises(ValidationError):
            Catalog.model_validate(payload)

    def test_same_category_and_name_are_rejected(self):
        payload = json.loads((ROOT / "examples/valid/workflow-catalog.json").read_text(encoding="utf-8"))
        duplicate = json.loads(json.dumps(payload["workflows"][0]))
        duplicate["id"] = "portrait-other"
        for version in duplicate["versions"]:
            version["release_tag"] = f"portrait-other-v{version['version']}"
        payload["workflows"].append(duplicate)
        with self.assertRaises(ValidationError):
            Catalog.model_validate(payload)

    def test_renaming_product_relocates_all_version_paths(self):
        catalog = Catalog.model_validate_json((ROOT / "examples/valid/workflow-catalog.json").read_bytes())
        existing = catalog.workflows[0]
        incoming = existing.model_copy(
            update={
                "name": "Portrait Studio",
                "repository_path": "workflows/Portrait/Portrait Studio",
                "versions": [],
            }
        )

        merged = merge_product(catalog, WorkflowProduct.model_validate(incoming.model_dump(mode="json")))

        product = merged.workflows[0]
        self.assertEqual(product.repository_path, "workflows/Portrait/Portrait Studio")
        self.assertEqual(
            product.versions[0].repository_path,
            "workflows/Portrait/Portrait Studio/versions/v1.12",
        )

    def test_duplicate_normalized_version_is_rejected(self):
        with self.assertRaises(ValidationError):
            Catalog.model_validate_json((ROOT / "examples/invalid/duplicate-normalized-version.json").read_bytes())

    def test_schema_is_valid_json(self):
        schema = json.loads((ROOT / "schemas/workflow-catalog.schema.json").read_text(encoding="utf-8"))
        self.assertEqual(schema["$schema"], "https://json-schema.org/draft/2020-12/schema")
