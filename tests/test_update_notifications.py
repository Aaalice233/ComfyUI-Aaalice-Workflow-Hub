import asyncio
import hashlib
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from tempfile import TemporaryDirectory
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, patch

from workflow_hub.api import _MAX_IGNORED_UPDATES, _notification_check_due, _pending_updates, _read_update_settings, _record_ignored_updates, _refresh_catalog_sources, _refresh_startup_source, _run_notification_check, _select_toast_items, _settings_payload
from workflow_hub.catalog import Catalog
from workflow_hub.github import ContentFile, GitHubError
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


class SubscriptionTokenTests(IsolatedAsyncioTestCase):
    async def _storage_with_subscription(self, folder: str) -> UserStorage:
        storage = UserStorage(Path(folder))
        await storage.write_json("subscriptions.json", [{
            "owner": "owner",
            "repo": "repo",
            "url": "https://github.com/owner/repo",
            "etag": "etag",
            "refreshed_at": "",
            "error": None,
        }])
        subscription_cache_path(storage, "owner", "repo").write_bytes(EXAMPLE.read_bytes())
        return storage

    async def test_refresh_uses_the_stored_github_token(self) -> None:
        with TemporaryDirectory() as folder:
            storage = await self._storage_with_subscription(folder)
            updated = with_version(load_catalog(), "9.9").model_dump_json().encode()
            client = SimpleNamespace(get_catalog=AsyncMock(return_value=ContentFile(content=updated, sha="", etag="new-etag")))
            factory = unittest.mock.Mock(return_value=client)
            with (
                patch("workflow_hub.service.tokens.get", new=AsyncMock(return_value="stored-token")),
                patch("workflow_hub.service.GitHubClient", new=factory),
            ):
                result = await refresh_subscription(storage, "owner", "repo", force=True)
            factory.assert_called_once_with("stored-token")
            self.assertTrue(result["changed"])

    async def test_refresh_falls_back_to_anonymous_on_401(self) -> None:
        with TemporaryDirectory() as folder:
            storage = await self._storage_with_subscription(folder)
            updated = with_version(load_catalog(), "9.9").model_dump_json().encode()
            authed = SimpleNamespace(get_catalog=AsyncMock(side_effect=GitHubError("bad credentials", 401)))
            anonymous = SimpleNamespace(get_catalog=AsyncMock(return_value=ContentFile(content=updated, sha="", etag="new-etag")))
            clients = iter([authed, anonymous])
            with (
                patch("workflow_hub.service.tokens.get", new=AsyncMock(return_value="revoked-token")),
                patch("workflow_hub.service.GitHubClient", side_effect=lambda token=None: next(clients)),
            ):
                result = await refresh_subscription(storage, "owner", "repo", force=True)
            self.assertTrue(result["changed"])
            anonymous.get_catalog.assert_awaited_once()


class StartupRefreshStateTests(IsolatedAsyncioTestCase):
    async def test_reports_catalog_changes_for_the_frontend_revalidation(self) -> None:
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
            subscription_cache_path(storage, "owner", "repo").write_bytes(EXAMPLE.read_bytes())
            with patch("workflow_hub.api.refresh_subscription", new=AsyncMock(return_value={"changed": True, "catalog_missing": False})):
                updates, changed, failed = await _refresh_startup_source(storage, "owner", "repo")
            self.assertEqual(updates, [])
            self.assertTrue(changed)
            self.assertFalse(failed)

    async def test_reports_removed_catalogs_and_refresh_failures(self) -> None:
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
            subscription_cache_path(storage, "owner", "repo").write_bytes(EXAMPLE.read_bytes())
            with patch("workflow_hub.api.refresh_subscription", new=AsyncMock(return_value={"changed": False, "catalog_missing": True})):
                _, removed, failed = await _refresh_startup_source(storage, "owner", "repo")
            self.assertTrue(removed)
            self.assertFalse(failed)
            with patch("workflow_hub.api.refresh_subscription", new=AsyncMock(side_effect=RuntimeError("offline"))):
                _, failed_changed, failed = await _refresh_startup_source(storage, "owner", "repo")
            self.assertTrue(failed_changed)
            self.assertTrue(failed)
            subscriptions = await storage.read_json("subscriptions.json", [])
            self.assertEqual(subscriptions[0]["error"], "subscription.refresh_failed")


class NotificationScheduleTests(IsolatedAsyncioTestCase):
    async def _storage_with_subscription(self, folder: str) -> UserStorage:
        storage = UserStorage(Path(folder))
        await storage.write_json("subscriptions.json", [{
            "owner": "owner",
            "repo": "repo",
            "url": "https://github.com/owner/repo",
            "etag": "etag",
            "refreshed_at": "",
            "error": None,
        }])
        subscription_cache_path(storage, "owner", "repo").write_bytes(EXAMPLE.read_bytes())
        return storage
    def test_interval_due_uses_the_configured_hours(self) -> None:
        now = datetime.now(timezone.utc)
        self.assertTrue(_notification_check_due({}, now, 24))
        self.assertFalse(_notification_check_due({"last_checked_at": (now - timedelta(hours=23)).isoformat()}, now, 24))
        self.assertTrue(_notification_check_due({"last_checked_at": (now - timedelta(hours=25)).isoformat()}, now, 24))

    async def test_check_revalidates_with_etag_and_persists_only_after_success(self) -> None:
        with TemporaryDirectory() as folder:
            storage = UserStorage(Path(folder))
            await storage.write_json("subscriptions.json", [{
                "owner": "owner",
                "repo": "repo",
                "url": "https://github.com/owner/repo",
                "etag": '"old-etag"',
                "refreshed_at": "",
                "error": None,
            }])
            with patch("workflow_hub.api.refresh_subscription", new=AsyncMock(return_value={"changed": False, "catalog_missing": False})) as refresh:
                result = await _run_notification_check(storage)
            self.assertTrue(result["checked"])
            self.assertIsNotNone(result["next_check_at"])
            refresh.assert_awaited_once_with(storage, "owner", "repo", force=False)
            self.assertTrue((storage.state_dir / "update-notifications.json").exists())

            with patch("workflow_hub.api.refresh_subscription", new=AsyncMock()) as refresh:
                result = await _run_notification_check(storage)
            self.assertFalse(result["checked"])
            refresh.assert_not_awaited()

    async def test_disabled_check_does_not_touch_sources(self) -> None:
        with TemporaryDirectory() as folder:
            storage = UserStorage(Path(folder))
            await storage.write_json("settings.json", {"auto_update_check": False, "update_check_interval_hours": 1})
            await storage.write_json("subscriptions.json", [{
                "owner": "owner",
                "repo": "repo",
                "url": "https://github.com/owner/repo",
                "refreshed_at": "",
                "error": None,
            }])
            with patch("workflow_hub.api.refresh_subscription", new=AsyncMock()) as refresh:
                result = await _run_notification_check(storage)
            self.assertFalse(result["enabled"])
            self.assertIsNone(result["next_check_at"])
            refresh.assert_not_awaited()

    async def test_failed_check_is_retryable(self) -> None:
        with TemporaryDirectory() as folder:
            storage = UserStorage(Path(folder))
            await storage.write_json("subscriptions.json", [{
                "owner": "owner",
                "repo": "repo",
                "url": "https://github.com/owner/repo",
                "refreshed_at": "",
                "error": None,
            }])
            with patch("workflow_hub.api.refresh_subscription", new=AsyncMock(side_effect=RuntimeError("offline"))) as refresh:
                result = await _run_notification_check(storage)
            self.assertFalse(result["checked"])
            self.assertTrue(result["failed"])
            self.assertFalse((storage.state_dir / "update-notifications.json").exists())
            refresh.assert_awaited_once()

    async def test_pending_updates_reflect_downloaded_versions(self) -> None:
        with TemporaryDirectory() as folder:
            storage = await self._storage_with_subscription(folder)
            self.assertEqual(
                await _pending_updates(storage),
                [{
                    "owner": "owner",
                    "repo": "repo",
                    "workflow_id": "portrait-basic",
                    "name": "Portrait Basic",
                    "version": "1.12",
                }],
            )
            downloaded = storage.workflows_root / "Portrait Basic.json"
            downloaded.write_text("{}", encoding="utf-8")
            await storage.write_json("installed.json", [{
                "owner": "owner",
                "repo": "repo",
                "workflow_id": "portrait-basic",
                "name": "Portrait Basic",
                "version": "1.12",
                "path": str(downloaded),
            }])
            self.assertEqual(await _pending_updates(storage), [])

    async def test_pending_updates_skip_ignored_versions(self) -> None:
        with TemporaryDirectory() as folder:
            storage = await self._storage_with_subscription(folder)
            await storage.write_json("update-ignores.json", {"ignored": ["owner/repo/portrait-basic/1.12"]})
            self.assertEqual(await _pending_updates(storage), [])

    async def test_pending_updates_reappear_for_newer_versions(self) -> None:
        with TemporaryDirectory() as folder:
            storage = await self._storage_with_subscription(folder)
            await storage.write_json("update-ignores.json", {"ignored": ["owner/repo/portrait-basic/1.12"]})
            subscription_cache_path(storage, "owner", "repo").write_bytes(
                with_version(load_catalog(), "1.13").model_dump_json().encode()
            )
            pending = await _pending_updates(storage)
            self.assertEqual([item["version"] for item in pending], ["1.13"])

    async def test_record_ignored_updates_dedupes_and_caps(self) -> None:
        with TemporaryDirectory() as folder:
            storage = UserStorage(Path(folder))
            await _record_ignored_updates(storage, ["owner/repo/a/1.0", "owner/repo/b/2.0"])
            await _record_ignored_updates(storage, ["owner/repo/a/1.0"])
            state = await storage.read_json("update-ignores.json", {})
            self.assertEqual(state["ignored"], ["owner/repo/a/1.0", "owner/repo/b/2.0"])
            await _record_ignored_updates(storage, [f"owner/repo/c/{idx}" for idx in range(_MAX_IGNORED_UPDATES)])
            state = await storage.read_json("update-ignores.json", {})
            self.assertEqual(len(state["ignored"]), _MAX_IGNORED_UPDATES)
            self.assertEqual(state["ignored"][-1], f"owner/repo/c/{_MAX_IGNORED_UPDATES - 1}")

    async def test_toast_items_fire_once_per_version_and_remind_after_a_week(self) -> None:
        now = datetime.now(timezone.utc)
        item = {"owner": "owner", "repo": "repo", "workflow_id": "portrait-basic", "name": "Portrait Basic", "version": "1.13"}
        notified: dict = {}

        # 已下载的版本不弹
        toast, changed = _select_toast_items([item], [], notified, now)
        self.assertEqual(toast, [])
        self.assertFalse(changed)

        # 新版本首次检测到 → 弹一次
        toast, changed = _select_toast_items([item], [item], notified, now)
        self.assertEqual(toast, [item])
        self.assertTrue(changed)

        # 同一版本再次检测到 → 不再弹
        toast, _ = _select_toast_items([item], [item], notified, now + timedelta(hours=1))
        self.assertEqual(toast, [])

        # 7 天内未下载不重复提醒，满 7 天提醒最后一次
        toast, _ = _select_toast_items([], [item], notified, now + timedelta(days=6))
        self.assertEqual(toast, [])
        toast, changed = _select_toast_items([], [item], notified, now + timedelta(days=8))
        self.assertEqual(toast, [item])
        self.assertTrue(changed)
        toast, _ = _select_toast_items([], [item], notified, now + timedelta(days=16))
        self.assertEqual(toast, [])

    async def test_notification_check_toasts_detected_version_once(self) -> None:
        with TemporaryDirectory() as folder:
            storage = await self._storage_with_subscription(folder)
            updated = with_version(load_catalog(), "9.9").model_dump_json().encode()

            async def apply_update(_storage: UserStorage, owner: str, repo: str, *, force: bool = False) -> dict:
                subscription_cache_path(_storage, owner, repo).write_bytes(updated)
                return {"changed": True, "catalog_missing": False}

            with patch("workflow_hub.api.refresh_subscription", new=AsyncMock(side_effect=apply_update)):
                result = await _run_notification_check(storage)
            self.assertTrue(result["checked"])
            self.assertEqual([item["version"] for item in result["items"]], ["9.9"])
            self.assertEqual([item["version"] for item in result["pending"]], ["9.9"])
            state = await storage.read_json("update-notifications.json", {})
            self.assertEqual(state["notified"]["owner/repo/portrait-basic"]["version"], "9.9")

            # 下一个检查周期目录无变化 → 不再为 9.9 弹 toast，角标仍在
            state["last_checked_at"] = (datetime.now(timezone.utc) - timedelta(hours=5)).isoformat()
            await storage.write_json("update-notifications.json", state)
            with patch("workflow_hub.api.refresh_subscription", new=AsyncMock(return_value={"changed": False, "catalog_missing": False})):
                result = await _run_notification_check(storage)
            self.assertEqual(result["items"], [])
            self.assertEqual([item["version"] for item in result["pending"]], ["9.9"])

    async def test_settings_are_normalized_and_expose_last_check(self) -> None:
        with TemporaryDirectory() as folder:
            storage = UserStorage(Path(folder))
            self.assertEqual(await _read_update_settings(storage), {
                "auto_update_check": True,
                "update_check_interval_hours": 4,
            })
            await storage.write_json("settings.json", {"auto_update_check": "yes", "update_check_interval_hours": 999})
            self.assertEqual(await _read_update_settings(storage), {
                "auto_update_check": True,
                "update_check_interval_hours": 4,
            })
            await storage.write_json("settings.json", {"auto_update_check": False, "update_check_interval_hours": 6})
            await storage.write_json("update-notifications.json", {"last_checked_at": "2026-08-04T10:00:00+00:00"})
            self.assertEqual(await _settings_payload(storage), {
                "auto_update_check": False,
                "update_check_interval_hours": 6,
                "last_checked_at": "2026-08-04T10:00:00+00:00",
            })


class CatalogRefreshEndpointTests(IsolatedAsyncioTestCase):
    async def test_refresh_all_uses_authoritative_forced_refreshes(self) -> None:
        with TemporaryDirectory() as folder:
            storage = UserStorage(Path(folder))
            await storage.write_json("subscriptions.json", [{
                "owner": "owner",
                "repo": "repo",
                "url": "https://github.com/owner/repo",
                "etag": '"old-etag"',
                "refreshed_at": "",
                "error": None,
            }])
            with patch(
                "workflow_hub.api.refresh_subscription",
                new=AsyncMock(return_value={"changed": True, "catalog_missing": False}),
            ) as refresh:
                result = await _refresh_catalog_sources(storage)

            self.assertEqual(result, {"changed": True, "failed": []})
            refresh.assert_awaited_once_with(storage, "owner", "repo", force=True)


class SubscriptionStateTests(IsolatedAsyncioTestCase):
    async def test_not_modified_catalog_keeps_cached_workflows(self) -> None:
        with TemporaryDirectory() as folder:
            storage = UserStorage(Path(folder))
            await storage.write_json("subscriptions.json", [{
                "owner": "owner",
                "repo": "repo",
                "url": "https://github.com/owner/repo",
                "default_branch": "main",
                "etag": "etag",
                "refreshed_at": "",
                "error": None,
            }])
            cache = subscription_cache_path(storage, "owner", "repo")
            cache.write_bytes(EXAMPLE.read_bytes())
            client = patch("workflow_hub.service.GitHubClient").start()
            client.return_value.get_catalog = AsyncMock(return_value=SimpleNamespace(not_modified=True, etag="etag"))
            try:
                result = await refresh_subscription(storage, "owner", "repo")
            finally:
                client.stop()
            self.assertFalse(result["catalog_missing"])
            self.assertTrue(cache.exists())
            self.assertTrue(await aggregate_catalog(storage))

    async def test_forced_refresh_does_not_send_cached_etag(self) -> None:
        with TemporaryDirectory() as folder:
            storage = UserStorage(Path(folder))
            content = EXAMPLE.read_bytes()
            await storage.write_json("subscriptions.json", [{
                "owner": "owner",
                "repo": "repo",
                "url": "https://github.com/owner/repo",
                "default_branch": "main",
                "etag": '"old-etag"',
                "catalog_hash": hashlib.sha256(content).hexdigest(),
                "refreshed_at": "",
                "error": None,
            }])
            subscription_cache_path(storage, "owner", "repo").write_bytes(content)
            with patch("workflow_hub.service.GitHubClient") as client:
                client.return_value.get_catalog = AsyncMock(
                    return_value=SimpleNamespace(content=content, etag='"new-etag"', not_modified=False)
                )
                await refresh_subscription(storage, "owner", "repo", force=True)
                client.return_value.get_catalog.assert_awaited_once_with(
                    "owner", "repo", None, force=True
                )

    async def test_refreshes_same_source_are_serialized(self) -> None:
        with TemporaryDirectory() as folder:
            storage = UserStorage(Path(folder))
            content = EXAMPLE.read_bytes()
            await storage.write_json("subscriptions.json", [{
                "owner": "owner",
                "repo": "repo",
                "url": "https://github.com/owner/repo",
                "default_branch": "main",
                "etag": '"old-etag"',
                "catalog_hash": hashlib.sha256(content).hexdigest(),
                "refreshed_at": "",
                "error": None,
            }])
            subscription_cache_path(storage, "owner", "repo").write_bytes(content)
            started = asyncio.Event()
            release = asyncio.Event()
            calls = 0

            async def catalog(*_args, **_kwargs):
                nonlocal calls
                calls += 1
                if calls == 1:
                    started.set()
                    await release.wait()
                return SimpleNamespace(content=content, etag=f'"etag-{calls}"', not_modified=False)

            with patch("workflow_hub.service.GitHubClient") as client:
                client.return_value.get_catalog.side_effect = catalog
                first = asyncio.create_task(refresh_subscription(storage, "owner", "repo"))
                await started.wait()
                second = asyncio.create_task(refresh_subscription(storage, "owner", "repo"))
                await asyncio.sleep(0)
                self.assertFalse(second.done())
                release.set()
                await asyncio.gather(first, second)

            self.assertEqual(calls, 2)

    async def test_catalog_hash_keeps_unchanged_catalog(self) -> None:
        with TemporaryDirectory() as folder:
            storage = UserStorage(Path(folder))
            content = EXAMPLE.read_bytes()
            await storage.write_json("subscriptions.json", [{
                "owner": "owner",
                "repo": "repo",
                "url": "https://github.com/owner/repo",
                "default_branch": "main",
                "etag": '"old-raw-etag"',
                "catalog_hash": hashlib.sha256(content).hexdigest(),
                "refreshed_at": "",
                "error": None,
            }])
            cache = subscription_cache_path(storage, "owner", "repo")
            cache.write_bytes(content)
            client = patch("workflow_hub.service.GitHubClient").start()
            client.return_value.get_catalog = AsyncMock(
                return_value=SimpleNamespace(content=content, etag='"new-api-etag"', not_modified=False)
            )
            try:
                result = await refresh_subscription(storage, "owner", "repo")
            finally:
                client.stop()
            self.assertFalse(result["changed"])
            self.assertFalse(result["catalog_missing"])
            subscriptions = await storage.read_json("subscriptions.json", [])
            self.assertEqual(subscriptions[0]["etag"], '"new-api-etag"')
            self.assertEqual(subscriptions[0]["catalog_hash"], hashlib.sha256(content).hexdigest())

    async def test_replaces_same_version_catalog_from_authoritative_api(self) -> None:
        with TemporaryDirectory() as folder:
            storage = UserStorage(Path(folder))
            previous_content = EXAMPLE.read_bytes()
            previous = load_catalog()
            previous_product = previous.workflows[0]
            replaced_version = previous_product.versions[0].model_copy(update={"changelog": "替换后的工作流"})
            current = previous.model_copy(update={
                "workflows": [previous_product.model_copy(update={"versions": [replaced_version]})],
            })
            current_content = current.model_dump_json().encode()
            await storage.write_json("subscriptions.json", [{
                "owner": "owner",
                "repo": "repo",
                "url": "https://github.com/owner/repo",
                "etag": '"old-etag"',
                "catalog_hash": hashlib.sha256(previous_content).hexdigest(),
                "refreshed_at": "",
                "error": None,
            }])
            subscription_cache_path(storage, "owner", "repo").write_bytes(previous_content)
            with patch("workflow_hub.service.GitHubClient") as client:
                client.return_value.get_catalog = AsyncMock(
                    return_value=SimpleNamespace(content=current_content, etag='"new-api-etag"', not_modified=False)
                )
                result = await refresh_subscription(storage, "owner", "repo", force=True)

            self.assertTrue(result["changed"])
            self.assertEqual(subscription_cache_path(storage, "owner", "repo").read_bytes(), current_content)
            subscriptions = await storage.read_json("subscriptions.json", [])
            self.assertNotIn("default_branch", subscriptions[0])
            self.assertEqual(subscriptions[0]["etag"], '"new-api-etag"')
            self.assertEqual(subscriptions[0]["catalog_hash"], hashlib.sha256(current_content).hexdigest())
            client.return_value.get_catalog.assert_awaited_once_with(
                "owner", "repo", None, force=True
            )

    async def test_removed_catalog_clears_cache_and_hides_old_workflows(self) -> None:
        with TemporaryDirectory() as folder:
            storage = UserStorage(Path(folder))
            await storage.write_json("subscriptions.json", [{
                "owner": "owner",
                "repo": "repo",
                "url": "https://github.com/owner/repo",
                "default_branch": "main",
                "etag": "etag",
                "refreshed_at": "",
                "error": None,
            }])
            cache = storage.cache_dir / "owner-repo.json"
            cache.write_bytes(EXAMPLE.read_bytes())
            client = patch("workflow_hub.service.GitHubClient").start()
            client.return_value.get_catalog = AsyncMock(return_value=None)
            try:
                result = await refresh_subscription(storage, "owner", "repo")
            finally:
                client.stop()
            self.assertTrue(result["catalog_missing"])
            self.assertFalse(cache.exists())
            self.assertEqual(await aggregate_catalog(storage), [])
            subscriptions = await storage.read_json("subscriptions.json", [])
            self.assertEqual(subscriptions[0]["error"], "subscription.catalog_missing")
