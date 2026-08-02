import hashlib
import json
import stat
import unittest
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory

from workflow_hub.packages import build_package, inspect_package, install_workflow


class PackageTests(unittest.TestCase):
    def test_build_validate_and_non_overwrite_install(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            package = root / "demo-v1.0.zip"
            result = build_package(package, {"schema_version": 1}, {"nodes": []}, "# 1.0")
            self.assertEqual(result["size"], package.stat().st_size)
            target, _ = install_workflow(package, root / "workflows", "owner", "repo", "demo", "Demo", "1.0", result["sha256"])
            self.assertTrue(target.exists())
            target.write_text('{"changed":true}', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "拒绝覆盖"):
                install_workflow(package, root / "workflows", "owner", "repo", "demo", "Demo", "1.0", result["sha256"])

    def test_install_preserves_filename_separator_from_manifest(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            package = root / "demo-v1.0.zip"
            result = build_package(
                package,
                {"schema_version": 1, "filename_separator": "_"},
                {"nodes": []},
                "# 1.0",
            )
            target, _ = install_workflow(package, root / "workflows", "owner", "repo", "demo", "Demo", "1.0", result["sha256"])
            self.assertEqual(target.name, "Demo_v1.0.json")

    def test_zip_slip_extra_files_and_symlink_are_rejected(self):
        cases = [("../workflow.json", 0), ("script.py", 0), ("workflow.json", (stat.S_IFLNK | 0o777) << 16)]
        for bad_name, external_attr in cases:
            with self.subTest(bad_name=bad_name), TemporaryDirectory() as folder:
                path = Path(folder) / "bad.zip"
                with zipfile.ZipFile(path, "w") as archive:
                    archive.writestr("manifest.json", "{}")
                    archive.writestr("CHANGELOG.md", "# change")
                    info = zipfile.ZipInfo(bad_name)
                    info.external_attr = external_attr
                    archive.writestr(info, json.dumps({"nodes": []}))
                with self.assertRaises(ValueError):
                    inspect_package(path)

    def test_hash_mismatch_is_rejected(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / "package.zip"
            build_package(path, {}, {}, "change")
            with self.assertRaisesRegex(ValueError, "SHA-256"):
                inspect_package(path, "0" * 64)

    def test_bundled_input_is_verified_installed_and_referenced(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            image = root / "source.png"
            image.write_bytes(b"\x89PNG\r\n\x1a\npayload")
            digest = hashlib.sha256(image.read_bytes()).hexdigest()
            archive_name = f"inputs/{digest[:12]}-source.png"
            manifest = {
                "inputs": [
                    {
                        "source": "source.png",
                        "archive": archive_name,
                        "sha256": digest,
                        "size": image.stat().st_size,
                        "node_ids": ["1"],
                    }
                ]
            }
            workflow = {"nodes": [{"id": 1, "type": "LoadImage", "widgets_values": ["source.png"]}]}
            package = root / "package.zip"
            result = build_package(
                package,
                manifest,
                workflow,
                "change",
                input_assets=[{"path": image, "archive": archive_name}],
            )
            target, _ = install_workflow(
                package,
                root / "workflows",
                "owner",
                "repo",
                "demo",
                "Demo",
                "1.0",
                result["sha256"],
                root / "input",
            )
            installed = json.loads(target.read_text(encoding="utf-8"))
            reference = installed["nodes"][0]["widgets_values"][0]
            self.assertEqual(reference, f"Workflow Hub/owner-repo/demo/{digest[:12]}-source.png")
            self.assertTrue((root / "input" / reference).is_file())
