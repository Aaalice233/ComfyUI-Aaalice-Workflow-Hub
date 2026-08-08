from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from workflow_hub import mirrors
from workflow_hub.mirrors import LauncherMirrors


GIT_MIRRORS = [
    {
        "src": ["comfyanonymous/ComfyUI", "Comfy-Org/ComfyUI", "https://gitee.com/AIGODLIKE/ComfyUI"],
        "dest": "https://jihulab.com/hanamizuki/comfyui",
    },
    {
        "src": ["https://github.com/foo/bar"],
        "dest": "https://gitee.com/mirror/bar",
    },
]

PIP_INDEX = [
    {"index_url": "https://pypi.doubanio.com/simple", "priority": 90},
    {"index_url": "https://mirrors.tuna.tsinghua.edu.cn/pypi/web/simple", "priority": 60},
    {"index_url": "http://mirrors.cloud.aliyuncs.com/pypi/simple", "priority": 1000},
]


def _mirrors(**overrides) -> LauncherMirrors:
    defaults = {
        "mirror_git": True,
        "git_mirrors": GIT_MIRRORS,
        "mirror_pypi": True,
        "pip_index": PIP_INDEX,
        "pip_trusted_host": ["mirrors.cloud.aliyuncs.com"],
    }
    defaults.update(overrides)
    return LauncherMirrors(**defaults)


class GitCloneCandidateTests(unittest.TestCase):
    def test_known_repository_prefers_mirror_and_keeps_canonical_fallback(self):
        candidates = _mirrors().git_clone_candidates("https://github.com/comfyanonymous/ComfyUI")
        self.assertEqual(
            candidates,
            ["https://jihulab.com/hanamizuki/comfyui", "https://github.com/comfyanonymous/ComfyUI"],
        )

    def test_src_matched_by_owner_repo_shorthand(self):
        candidates = _mirrors().git_clone_candidates("https://github.com/Foo/Bar")
        self.assertEqual(candidates[0], "https://gitee.com/mirror/bar")

    def test_unknown_repository_uses_canonical_only(self):
        candidates = _mirrors().git_clone_candidates("https://github.com/someone/unknown")
        self.assertEqual(candidates, ["https://github.com/someone/unknown"])

    def test_switch_off_disables_mirror(self):
        candidates = _mirrors(mirror_git=False).git_clone_candidates("https://github.com/comfyanonymous/ComfyUI")
        self.assertEqual(candidates, ["https://github.com/comfyanonymous/ComfyUI"])


class CanonicalRemoteTests(unittest.TestCase):
    def setUp(self):
        self.mirrors = _mirrors()

    def test_plain_github(self):
        self.assertEqual(
            self.mirrors.canonical_remote_url("https://github.com/Owner/Repo.git"),
            "https://github.com/Owner/Repo",
        )

    def test_ssh_forms(self):
        self.assertEqual(
            self.mirrors.canonical_remote_url("git@github.com:Owner/Repo.git"),
            "https://github.com/Owner/Repo",
        )
        self.assertEqual(
            self.mirrors.canonical_remote_url("ssh://git@github.com/Owner/Repo"),
            "https://github.com/Owner/Repo",
        )

    def test_proxy_prefix_forms(self):
        self.assertEqual(
            self.mirrors.canonical_remote_url("https://ghproxy.net/https://github.com/Owner/Repo"),
            "https://github.com/Owner/Repo",
        )
        self.assertEqual(
            self.mirrors.canonical_remote_url("https://ghfast.top/https://github.com/Owner/Repo.git"),
            "https://github.com/Owner/Repo",
        )

    def test_launcher_mirror_dest_maps_back_to_github(self):
        self.assertEqual(
            self.mirrors.canonical_remote_url("https://jihulab.com/hanamizuki/comfyui"),
            "https://github.com/comfyanonymous/ComfyUI",
        )
        self.assertEqual(
            self.mirrors.canonical_remote_url("https://gitee.com/AIGODLIKE/ComfyUI"),
            "https://github.com/comfyanonymous/ComfyUI",
        )

    def test_unknown_non_github_remote(self):
        self.assertIsNone(self.mirrors.canonical_remote_url("https://gitlab.com/owner/repo"))
        self.assertIsNone(self.mirrors.canonical_remote_url(""))


class PipMirrorTests(unittest.TestCase):
    def test_candidates_sorted_by_priority_with_intranet_last(self):
        candidates = _mirrors().pip_index_candidates()
        urls = [url for url, _intranet in candidates]
        self.assertEqual(urls[0], "http://mirrors.cloud.aliyuncs.com/pypi/simple")
        self.assertTrue(candidates[0][1])
        self.assertFalse(candidates[1][1])

    def test_switch_off_returns_no_candidates(self):
        self.assertEqual(_mirrors(mirror_pypi=False).pip_index_candidates(), [])

    def test_select_pip_arguments_prefers_first_reachable_public(self):
        async def fake_reachable(urls):
            return urls[0] if urls else None

        instance = _mirrors()
        with patch.object(mirrors, "_first_reachable", side_effect=fake_reachable):
            import asyncio

            arguments = asyncio.run(instance.select_pip_arguments())
        self.assertEqual(arguments, ["--index-url", "https://pypi.doubanio.com/simple"])

    def test_select_pip_arguments_adds_trusted_host_for_http(self):
        async def fake_reachable(urls):
            return None if "aliyuncs" not in urls[0] else urls[0]

        calls = []

        async def router(urls):
            calls.append(urls)
            if any("aliyuncs" in url for url in urls):
                return urls[0]
            return None

        instance = _mirrors()
        with patch.object(mirrors, "_first_reachable", side_effect=router):
            import asyncio

            arguments = asyncio.run(instance.select_pip_arguments())
        # 公网镜像全部不可达时才探测内网地址
        self.assertEqual(len(calls), 2)
        self.assertEqual(
            arguments,
            ["--index-url", "http://mirrors.cloud.aliyuncs.com/pypi/simple", "--trusted-host", "mirrors.cloud.aliyuncs.com"],
        )

    def test_select_pip_arguments_empty_when_nothing_reachable(self):
        async def never(_urls):
            return None

        instance = _mirrors()
        with patch.object(mirrors, "_first_reachable", side_effect=never):
            import asyncio

            self.assertEqual(asyncio.run(instance.select_pip_arguments()), [])


class LauncherDetectionTests(unittest.TestCase):
    def setUp(self):
        mirrors.reset_cache()

    def tearDown(self):
        mirrors.reset_cache()

    def _write_launcher(self, root: Path, preference: dict, data: dict) -> Path:
        launcher = root / ".launcher"
        launcher.mkdir(parents=True)
        (launcher / "preference.json").write_text(json.dumps(preference), encoding="utf-8")
        (launcher / "data.json").write_text(json.dumps(data), encoding="utf-8")
        return launcher

    def test_active_returns_empty_outside_launcher(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(mirrors, "_launcher_directories", return_value=[Path(tmp)]):
                active = mirrors.active()
        self.assertFalse(active.available)

    def test_active_reads_preference_and_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_launcher(
                root,
                {"network_preference": {"mirror_git": True, "mirror_pypi": False}},
                {"mirrors": {"git_mirrors": GIT_MIRRORS, "pip_index": PIP_INDEX}},
            )
            with patch.object(mirrors, "_launcher_directories", return_value=[root / ".launcher"]):
                active = mirrors.active()
            self.assertTrue(active.mirror_git)
            self.assertFalse(active.mirror_pypi)
            self.assertEqual(len(active.git_mirrors), 2)

    def test_active_reloads_on_mtime_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            launcher = self._write_launcher(
                root,
                {"network_preference": {"mirror_git": False}},
                {"mirrors": {}},
            )
            with patch.object(mirrors, "_launcher_directories", return_value=[launcher]):
                self.assertFalse(mirrors.active().mirror_git)
                import os
                import time

                time.sleep(0.01)
                (launcher / "preference.json").write_text(
                    json.dumps({"network_preference": {"mirror_git": True}}), encoding="utf-8"
                )
                os.utime(launcher / "preference.json")
                self.assertTrue(mirrors.active().mirror_git)


if __name__ == "__main__":
    unittest.main()
