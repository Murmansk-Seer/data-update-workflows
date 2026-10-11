import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import httpx
from PIL import Image

from scripts.seer_unity_assets import chip_recovery as recovery
from scripts.seer_unity_assets.autocard_chips import (
    CHIP_ICON_DIRECTORY,
    CHIP_ICON_MANIFEST,
    chip_icon_file_is_current,
)

VERSION = "20261009171440"
BUNDLE = b"official bundle"
DIGEST = hashlib.md5(BUNDLE).hexdigest()


def manifest(version=VERSION):
    return {
        "PackageName": "DefaultPackage",
        "PackageVersion": version,
        "BundleList": [
            {
                "BundleName": "game_ui_autocard",
                "FileHash": DIGEST,
                "FileSize": len(BUNDLE),
            }
        ],
    }


def export(bundle, root, version):
    assert bundle.read_bytes() == BUNDLE
    target = root / CHIP_ICON_DIRECTORY
    target.mkdir(parents=True)
    Image.new("RGBA", (8, 8), "white").save(target / "autocardChip_115.png")
    record = root / CHIP_ICON_MANIFEST
    record.parent.mkdir(parents=True)
    record.write_text(
        json.dumps(
            {"schema_version": 1, "package_version": version, "sprite_ids": [115]}
        )
    )
    return 1


class RecoveryTests(unittest.TestCase):
    def test_missing_bundle_downloads_only_manifest_and_chip(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with (
                patch.object(
                    recovery, "download_bytes", side_effect=[b"manifest", BUNDLE]
                ) as download,
                patch.object(recovery, "NewseerManifestParser") as parser,
                patch.object(recovery, "extract_chip_icons", side_effect=export),
            ):
                parser.return_value.return_value = manifest()
                recovery.recover_chip_icons(root, VERSION)
                self.assertTrue(chip_icon_file_is_current(root, VERSION))
                self.assertEqual(download.call_count, 2)
                self.assertEqual(download.call_args.args, (recovery.BASE_URL + DIGEST,))
                recovery.recover_chip_icons(root, VERSION)
                self.assertEqual(download.call_count, 2)

    def test_local_verified_bundle_is_reused_but_icons_reextracted(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            local = root / "newseer/assetbundles/DefaultPackage/game_ui_autocard"
            local.parent.mkdir(parents=True)
            local.write_bytes(BUNDLE)
            with (
                patch.object(
                    recovery, "download_bytes", return_value=b"manifest"
                ) as download,
                patch.object(recovery, "NewseerManifestParser") as parser,
                patch.object(
                    recovery, "extract_chip_icons", side_effect=export
                ) as extract,
            ):
                parser.return_value.return_value = manifest()
                recovery.recover_chip_icons(root, VERSION)
                download.assert_called_once()
                self.assertEqual(extract.call_args.args[0], local)

    def test_invalid_download_does_not_replace_published_manifest(self):
        for mode in ("hash", "version", "extract"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                record = root / CHIP_ICON_MANIFEST
                record.parent.mkdir(parents=True)
                record.write_text("old published record")
                with (
                    patch.object(
                        recovery,
                        "download_bytes",
                        side_effect=[
                            b"manifest",
                            b"wrong" if mode == "hash" else BUNDLE,
                        ],
                    ),
                    patch.object(recovery, "NewseerManifestParser") as parser,
                    patch.object(
                        recovery,
                        "extract_chip_icons",
                        side_effect=ValueError("bad atlas"),
                    ),
                ):
                    parser.return_value.return_value = manifest(
                        "wrong" if mode == "version" else VERSION
                    )
                    with self.assertRaises(ValueError):
                        recovery.recover_chip_icons(root, VERSION)
                self.assertEqual(record.read_text(), "old published record")

    def test_png_corruption_and_transparency_trigger_recovery(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            record = root / CHIP_ICON_MANIFEST
            record.parent.mkdir(parents=True)
            record.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "package_version": VERSION,
                        "sprite_ids": [115],
                    }
                )
            )
            icon = root / CHIP_ICON_DIRECTORY / "autocardChip_115.png"
            icon.parent.mkdir(parents=True)
            for data in (None, b"broken"):
                if data is None:
                    Image.new("RGBA", (8, 8)).save(icon)
                else:
                    icon.write_bytes(data)
                self.assertFalse(chip_icon_file_is_current(root, VERSION))

    def test_download_has_three_total_attempts(self):
        with (
            patch.object(
                recovery.httpx, "get", side_effect=httpx.ConnectTimeout("timeout")
            ) as request,
            patch.object(recovery.time, "sleep"),
        ):
            with self.assertRaises(httpx.ConnectTimeout):
                recovery.download_bytes("https://official.test/bundle")
            self.assertEqual(request.call_count, 3)
