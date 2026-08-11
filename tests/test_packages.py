import hashlib
import json
import stat
import unittest
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from workflow_hub.errors import UserFacingError
from workflow_hub.packages import build_package, inspect_package, install_workflow


class PackageTests(unittest.TestCase):
    def test_build_validate_and_non_overwrite_install(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            package = root / "demo-v1.0.zip"
            result = build_package(package, {"schema_version": 1}, {"nodes": []}, "# 1.0")
            self.assertEqual(result["size"], package.stat().st_size)
            target, _ = install_workflow(package, root / "workflows", "Demo", "1.0", result["sha256"])
            self.assertEqual(target, (root / "workflows" / "Demo-v1.0.json").resolve())
            target.write_text('{"changed":true}', encoding="utf-8")
            with self.assertRaises(UserFacingError):
                install_workflow(package, root / "workflows", "Demo", "1.0", result["sha256"])

    def test_install_falls_back_when_windows_hard_links_are_unsupported(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            image = root / "source.png"
            image.write_bytes(b"image")
            digest = hashlib.sha256(image.read_bytes()).hexdigest()
            archive_name = f"inputs/{digest[:12]}-source.png"
            package = root / "package.zip"
            result = build_package(
                package,
                {"inputs": [{"source": "source.png", "archive": archive_name, "sha256": digest, "size": image.stat().st_size}]},
                {"nodes": [{"id": 1, "type": "LoadImage", "widgets_values": ["source.png"]}]},
                "change",
                input_assets=[{"path": image, "archive": archive_name}],
            )
            hard_link_error = OSError("Incorrect function")
            hard_link_error.winerror = 1
            with patch("workflow_hub.packages.os.link", side_effect=hard_link_error):
                target, _ = install_workflow(
                    package,
                    root / "workflows",
                    "Demo",
                    "1.0",
                    result["sha256"],
                    root / "input",
                )
            self.assertTrue(target.is_file())
            self.assertEqual((root / "input" / "source.png").read_bytes(), b"image")

    def test_install_fallback_does_not_overwrite_a_competing_file(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            package = root / "package.zip"
            result = build_package(package, {}, {"nodes": []}, "change")
            hard_link_error = OSError("Incorrect function")
            hard_link_error.winerror = 1

            def create_competing_file(_source, target):
                Path(target).write_text("competing-content", encoding="utf-8")
                raise hard_link_error

            with patch("workflow_hub.packages.os.link", side_effect=create_competing_file):
                with self.assertRaises(UserFacingError) as caught:
                    install_workflow(package, root / "workflows", "Demo", "1.0", result["sha256"])
            target = root / "workflows" / "Demo-v1.0.json"
            self.assertEqual(caught.exception.code, "subscription.workflow_file_conflict")
            self.assertEqual(target.read_text(encoding="utf-8"), "competing-content")

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
            target, _ = install_workflow(package, root / "workflows", "Demo", "1.0", result["sha256"])
            self.assertEqual(target, (root / "workflows" / "Demo_v1.0.json").resolve())

    def test_existing_input_with_different_content_is_not_overwritten(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            image = root / "source.png"
            image.write_bytes(b"new-image")
            digest = hashlib.sha256(image.read_bytes()).hexdigest()
            archive_name = f"inputs/{digest[:12]}-source.png"
            package = root / "package.zip"
            result = build_package(
                package,
                {"inputs": [{"source": "source.png", "archive": archive_name, "sha256": digest, "size": image.stat().st_size}]},
                {"nodes": [{"id": 1, "type": "LoadImage", "widgets_values": ["source.png"]}]},
                "change",
                input_assets=[{"path": image, "archive": archive_name}],
            )
            existing = root / "input" / "source.png"
            existing.parent.mkdir()
            existing.write_bytes(b"existing-image")
            with self.assertRaises(UserFacingError) as caught:
                install_workflow(package, root / "workflows", "Demo", "1.0", result["sha256"], root / "input")
            self.assertEqual(caught.exception.code, "subscription.input_file_conflict")
            self.assertEqual(existing.read_bytes(), b"existing-image")
            self.assertFalse((root / "workflows" / "Demo-v1.0.json").exists())

    def test_manifest_rejects_unsafe_input_source(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            image = root / "source.png"
            image.write_bytes(b"image")
            digest = hashlib.sha256(image.read_bytes()).hexdigest()
            archive_name = f"inputs/{digest[:12]}-source.png"
            package = root / "package.zip"
            with self.assertRaises(ValueError):
                build_package(
                    package,
                    {"inputs": [{"source": "../source.png", "archive": archive_name, "sha256": digest, "size": image.stat().st_size}]},
                    {"nodes": []},
                    "change",
                    input_assets=[{"path": image, "archive": archive_name}],
                )

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

    def test_multiple_preview_files_are_rejected(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / "previews.zip"
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("manifest.json", "{}")
                archive.writestr("CHANGELOG.md", "# change")
                archive.writestr("workflow.json", "{}")
                archive.writestr("preview.png", b"png")
                archive.writestr("preview.jpg", b"jpg")
            with self.assertRaisesRegex(ValueError, "预览图"):
                inspect_package(path)

    def test_hash_mismatch_is_rejected(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / "package.zip"
            build_package(path, {}, {}, "change")
            with self.assertRaisesRegex(ValueError, "SHA-256"):
                inspect_package(path, "0" * 64)

    def test_bundled_input_is_verified_installed_without_rewriting_reference(self):
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
                "Demo",
                "1.0",
                result["sha256"],
                root / "input",
            )
            installed = json.loads(target.read_text(encoding="utf-8"))
            reference = installed["nodes"][0]["widgets_values"][0]
            self.assertEqual(target, (root / "workflows" / "Demo-v1.0.json").resolve())
            self.assertEqual(reference, "source.png")
            self.assertTrue((root / "input" / "source.png").is_file())
