import hashlib
import unittest
from pathlib import Path
from types import SimpleNamespace
from tempfile import TemporaryDirectory
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, patch

from workflow_hub.catalog import Catalog
from workflow_hub.service import aggregate_catalog, find_catalog_updates, refresh_subscription, reveal_in_file_manager, subscription_cache_path
from workflow_hub.storage import UserStorage


EXAMPLE = Path(__file__).resolve().parent.parent / "examples" / "valid" / "workflow-catalog.json"


def load_catalog() -> Catalog:
    return Catalog.model_validate_json(EXAMPLE.read_bytes())


def with_version(catalog: Catalog, version: str) -> Catalog:
    product = catalog.workflows[0]
    added = product.versions[0].model_copy(
        update={
            "version": version,
            "release_tag": f"{product.id}-v{version}",
            "repository_path": f"{product.repository_path}/versions/v{version}",
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


class SubscriptionStateTests(IsolatedAsyncioTestCase):
    async def test_not_modified_catalog_keeps_cached_workflows(self) -> None:
        with TemporaryDirectory() as folder:
            storage = UserStorage(Path(folder))
            await storage.write_json("subscriptions.json", [{
                "owner": "owner",
                "repo": "repo",
                "url": "https://github.com/owner/repo",
                "etag": "etag",
                "refreshed_at": "",
                "error": None,
            }])
            cache = subscription_cache_path(storage, "owner", "repo")
            cache.write_bytes(EXAMPLE.read_bytes())
            client = patch("workflow_hub.service.GitHubClient").start()
            client.return_value.get_raw_catalog = AsyncMock(return_value=SimpleNamespace(not_modified=True, etag="etag"))
            try:
                result = await refresh_subscription(storage, "owner", "repo")
            finally:
                client.stop()
            self.assertFalse(result["catalog_missing"])
            self.assertTrue(cache.exists())
            self.assertTrue(await aggregate_catalog(storage))

    async def test_raw_catalog_hash_keeps_unchanged_catalog(self) -> None:
        with TemporaryDirectory() as folder:
            storage = UserStorage(Path(folder))
            content = EXAMPLE.read_bytes()
            await storage.write_json("subscriptions.json", [{
                "owner": "owner",
                "repo": "repo",
                "url": "https://github.com/owner/repo",
                "etag": '"old-raw-etag"',
                "catalog_hash": hashlib.sha256(content).hexdigest(),
                "refreshed_at": "",
                "error": None,
            }])
            cache = subscription_cache_path(storage, "owner", "repo")
            cache.write_bytes(content)
            client = patch("workflow_hub.service.GitHubClient").start()
            client.return_value.get_raw_catalog = AsyncMock(
                return_value=SimpleNamespace(content=content, etag='"new-raw-etag"', not_modified=False)
            )
            try:
                result = await refresh_subscription(storage, "owner", "repo")
            finally:
                client.stop()
            self.assertFalse(result["changed"])
            self.assertFalse(result["catalog_missing"])
            subscriptions = await storage.read_json("subscriptions.json", [])
            self.assertEqual(subscriptions[0]["etag"], '"new-raw-etag"')
            self.assertEqual(subscriptions[0]["catalog_hash"], hashlib.sha256(content).hexdigest())

    async def test_removed_catalog_clears_cache_and_hides_old_workflows(self) -> None:
        with TemporaryDirectory() as folder:
            storage = UserStorage(Path(folder))
            await storage.write_json("subscriptions.json", [{
                "owner": "owner",
                "repo": "repo",
                "url": "https://github.com/owner/repo",
                "etag": "etag",
                "refreshed_at": "",
                "error": None,
            }])
            cache = storage.cache_dir / "owner-repo.json"
            cache.write_bytes(EXAMPLE.read_bytes())
            client = patch("workflow_hub.service.GitHubClient").start()
            client.return_value.get_raw_catalog = AsyncMock(return_value=None)
            try:
                result = await refresh_subscription(storage, "owner", "repo")
            finally:
                client.stop()
            self.assertTrue(result["catalog_missing"])
            self.assertFalse(cache.exists())
            self.assertEqual(await aggregate_catalog(storage), [])
            subscriptions = await storage.read_json("subscriptions.json", [])
            self.assertEqual(subscriptions[0]["error"], "subscription.catalog_missing")
