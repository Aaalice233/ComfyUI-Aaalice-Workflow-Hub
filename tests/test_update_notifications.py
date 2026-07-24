import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from workflow_hub.catalog import Catalog
from workflow_hub.service import find_catalog_updates, reveal_in_file_manager


EXAMPLE = Path(__file__).resolve().parent.parent / "examples" / "valid" / "workflow-catalog.json"


def load_catalog() -> Catalog:
    return Catalog.model_validate_json(EXAMPLE.read_bytes())


def with_version(catalog: Catalog, version: str) -> Catalog:
    product = catalog.workflows[0]
    added = product.versions[0].model_copy(
        update={
            "version": version,
            "release_tag": f"{product.id}-v{version}",
        }
    )
    updated = product.model_copy(update={"versions": product.versions + [added]})
    return catalog.model_copy(update={"workflows": [updated]})


class UpdateNotificationTests(unittest.TestCase):
    def test_finds_only_the_latest_newer_version(self) -> None:
        previous = load_catalog()
        current = with_version(with_version(previous, "1.13"), "2.0")

        self.assertEqual(
            find_catalog_updates(previous, current, "Aaalice233", "workflows"),
            [
                {
                    "owner": "Aaalice233",
                    "repo": "workflows",
                    "workflow_id": "portrait-basic",
                    "name": "Portrait Basic",
                    "version": "2.0",
                }
            ],
        )

    def test_ignores_metadata_changes_and_archived_workflows(self) -> None:
        previous = load_catalog()
        renamed = previous.workflows[0].model_copy(update={"name": "Renamed"})
        metadata_only = previous.model_copy(update={"workflows": [renamed]})
        archived_product = with_version(previous, "1.13").workflows[0].model_copy(update={"archived": True})
        archived = previous.model_copy(update={"workflows": [archived_product]})

        self.assertEqual(find_catalog_updates(previous, metadata_only, "owner", "repo"), [])
        self.assertEqual(find_catalog_updates(previous, archived, "owner", "repo"), [])

    def test_reveals_the_downloaded_file_directory(self) -> None:
        with (
            TemporaryDirectory() as folder,
            patch("workflow_hub.service.sys.platform", "win32"),
            patch("workflow_hub.service.os.startfile", create=True) as startfile,
        ):
            target = Path(folder) / "workflow.json"
            target.write_text("{}", encoding="utf-8")

            reveal_in_file_manager(target)

            startfile.assert_called_once_with(str(target.parent))

    def test_rejects_a_missing_downloaded_file(self) -> None:
        with self.assertRaisesRegex(ValueError, "本地工作流文件不存在"):
            reveal_in_file_manager(Path("missing-workflow.json"))
