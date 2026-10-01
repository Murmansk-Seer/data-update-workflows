import hashlib
import asyncio
from concurrent.futures import CancelledError
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, AsyncMock

import httpx
from albi0 import RemoteManifestSnapshot
from albi0.update.version import Manifest, ManifestItem, LocalFileName
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
        "PackageAssetCount": 0,
        "PackageAssetInfos": [],
        "PackageBundleCount": 1,
        "BundleList": [
            {
                "BundleName": "game_ui_autocard",
                "FileHash": DIGEST,
                "FileSize": len(BUNDLE),
            }
        ],
    }


def snapshot(version=VERSION):
    return RemoteManifestSnapshot.from_manifest(
        Manifest(
            version,
            {
                LocalFileName(
                    "newseer/assetbundles/DefaultPackage/game_ui_autocard"
                ): ManifestItem(
                    recovery.BASE_URL + DIGEST,
                    "game_ui_autocard.bundle",
                    DIGEST.encode(),
                    len(BUNDLE),
                )
            },
        )
    )


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
        self.assertEqual(
            self.network([httpx.ConnectTimeout("timeout")], error=httpx.ConnectTimeout),
            3,
        )

    def network(self, outcomes, *, error=None, resource=False, deadline=None):
        calls = []
        original = httpx.AsyncClient
        original_sleep = asyncio.sleep

        def handle(request):
            item = outcomes[min(len(calls), len(outcomes) - 1)]
            calls.append(request)
            if isinstance(item, BaseException):
                raise item
            code, body = item
            return httpx.Response(code, content=body)

        async def slow(request):
            calls.append(request)
            await original_sleep(5)
            return httpx.Response(200)

        def client(**kwargs):
            self.assertEqual(kwargs["timeout"].connect, 15)
            self.assertEqual(kwargs["timeout"].read, 180 if resource else 30)
            return original(
                **kwargs, transport=httpx.MockTransport(slow if deadline else handle)
            )

        with (
            patch.object(recovery.httpx, "AsyncClient", side_effect=client),
            patch.object(recovery.asyncio, "sleep", new=AsyncMock()),
            patch.object(recovery, "METADATA_ATTEMPT_SECONDS", deadline or 60),
        ):
            kwargs = {"package_version": VERSION}
            if resource:
                kwargs.update(expected_size=len(BUNDLE), expected_md5=DIGEST)
            if error:
                with self.assertRaises(error):
                    recovery.download_bytes(
                        "https://official.test/bundle?token=do-not-log", **kwargs
                    )
            else:
                self.assertEqual(
                    recovery.download_bytes("https://official.test/bundle", **kwargs),
                    BUNDLE,
                )
        return len(calls)

    def test_status_read_failure_and_third_success(self):
        for status in (408, 429, 503):
            self.assertEqual(
                self.network([(status, b"")], error=httpx.HTTPStatusError), 3
            )
            self.assertEqual(
                self.network([(status, b""), (status, b""), (200, BUNDLE)]), 3
            )
        self.assertEqual(self.network([(404, b"")], error=httpx.HTTPStatusError), 1)
        self.assertEqual(
            self.network([httpx.ReadError("disconnected")], error=httpx.ReadError), 3
        )

    def test_hash_and_size_share_the_request_budget(self):
        self.assertEqual(
            self.network(
                [(200, b"wrong")], resource=True, error=recovery.ChipIntegrityError
            ),
            3,
        )
        self.assertEqual(
            self.network(
                [(200, b"wrong"), (200, b"wrong"), (200, BUNDLE)], resource=True
            ),
            3,
        )
        self.assertEqual(self.network([(200, BUNDLE)], resource=True), 1)

    def test_total_deadline_program_errors_and_cancel(self):
        self.assertEqual(self.network([], deadline=0.01, error=TimeoutError), 3)
        self.assertEqual(self.network([ValueError("bug")], error=ValueError), 1)
        self.assertEqual(
            self.network([asyncio.CancelledError()], error=CancelledError), 1
        )

    def test_same_run_snapshot_never_requests_manifest_even_if_old_delta_has_no_chip(
        self,
    ):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            old = root / "package-manifests/DefaultPackage.json"
            old.parent.mkdir()
            old.write_text('{"version":"old","items":{}}')
            with (
                patch.object(
                    recovery, "download_bytes", return_value=BUNDLE
                ) as download,
                patch.object(recovery, "extract_chip_icons", side_effect=export),
            ):
                recovery.recover_chip_icons(root, VERSION, manifest_snapshot=snapshot())
                download.assert_called_once_with(
                    recovery.BASE_URL + DIGEST,
                    package_version=VERSION,
                    expected_size=len(BUNDLE),
                    expected_md5=DIGEST,
                )
                self.assertEqual(old.read_text(), '{"version":"old","items":{}}')

    def test_supplied_wrong_version_never_falls_back_to_network(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.object(recovery, "download_bytes") as download,
            patch.object(recovery, "extract_chip_icons") as extract,
        ):
            with self.assertRaisesRegex(ValueError, "version mismatch"):
                recovery.recover_chip_icons(
                    Path(directory),
                    VERSION,
                    manifest_snapshot=snapshot("20261001000000"),
                )
            download.assert_not_called()
            extract.assert_not_called()

    def test_valid_local_bundle_with_changed_version_requires_actual_reextract(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            local = root / "newseer/assetbundles/DefaultPackage/game_ui_autocard"
            local.parent.mkdir(parents=True)
            local.write_bytes(BUNDLE)
            export(local, root, "20261001000000")
            with (
                patch.object(recovery, "download_bytes") as download,
                patch.object(
                    recovery, "extract_chip_icons", side_effect=export
                ) as extract,
            ):
                recovery.recover_chip_icons(root, VERSION, manifest_snapshot=snapshot())
                download.assert_not_called()
                extract.assert_called_once()
                self.assertTrue(chip_icon_file_is_current(root, VERSION))

    def test_network_failure_never_extracts_or_replaces_record(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            record = root / CHIP_ICON_MANIFEST
            record.parent.mkdir(parents=True)
            record.write_text("old")
            with (
                patch.object(
                    recovery,
                    "download_bytes",
                    side_effect=httpx.ConnectTimeout("all attempts exhausted"),
                ),
                patch.object(recovery, "extract_chip_icons") as extract,
            ):
                with self.assertRaises(httpx.ConnectTimeout):
                    recovery.recover_chip_icons(
                        root, VERSION, manifest_snapshot=snapshot()
                    )
                extract.assert_not_called()
            self.assertEqual(record.read_text(), "old")

    def test_request_logs_identify_stage_and_redact_query(self):
        messages = []
        sink = recovery.logger.add(lambda message: messages.append(str(message)))
        try:
            self.assertEqual(self.network([(404, b"")], error=httpx.HTTPStatusError), 1)
        finally:
            recovery.logger.remove(sink)
        logs = "\n".join(messages)
        self.assertIn("chip_manifest", logs)
        self.assertIn(f"version={VERSION}", logs)
        self.assertIn("attempt=1/3", logs)
        self.assertNotIn("do-not-log", logs)
        self.assertNotIn("token=", logs)
