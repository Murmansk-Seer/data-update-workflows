from contextlib import asynccontextmanager
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from scripts.seer_unity_assets.update import process_package


class AssetExtractionTests(unittest.IsolatedAsyncioTestCase):
    async def test_chip_bundle_uses_atlas_exporter_instead_of_generic_mesh_export(self):
        @asynccontextmanager
        async def session():
            yield

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bundle_dir = root / "newseer/assetbundles/DefaultPackage"
            bundle_dir.mkdir(parents=True)
            bundle = bundle_dir / "game_ui_autocard"
            bundle.write_bytes(b"test")
            config = {
                "updater_name": "newseer.default",
                "extractor_name": "newseer",
                "update_args": ["game_ui_autocard.bundle"],
                "skip_extract": False,
            }
            with (
                patch("scripts.seer_unity_assets.update.albi0.session", session),
                patch(
                    "scripts.seer_unity_assets.update.albi0.update_resources",
                    AsyncMock(),
                ),
                patch(
                    "scripts.seer_unity_assets.update.albi0.extract_assets", AsyncMock()
                ) as generic,
                patch(
                    "scripts.seer_unity_assets.update.extract_chip_icons",
                    return_value=146,
                ) as export,
                patch(
                    "scripts.seer_unity_assets.update.chip_icon_file_is_current",
                    return_value=True,
                ),
            ):
                await process_package(
                    package_name="DefaultPackage",
                    config=config,
                    repo_path=root,
                    remote_version="v1",
                )
            generic.assert_not_awaited()
            export.assert_called_once_with(bundle, root, "v1")

    async def test_extraction_serializes_duplicate_sprite_and_texture_paths(self):
        @asynccontextmanager
        async def session():
            yield

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bundle_dir = root / "newseer/assetbundles/DefaultPackage"
            bundle_dir.mkdir(parents=True)
            (bundle_dir / "bundle").write_bytes(b"test")
            update_resources = AsyncMock()
            extract_assets = AsyncMock()
            config = {
                "updater_name": "newseer.default",
                "extractor_name": "newseer",
                "update_args": [],
                "skip_extract": False,
            }
            with (
                patch("scripts.seer_unity_assets.update.albi0.session", session),
                patch(
                    "scripts.seer_unity_assets.update.albi0.update_resources",
                    update_resources,
                ),
                patch(
                    "scripts.seer_unity_assets.update.albi0.extract_assets",
                    extract_assets,
                ),
            ):
                await process_package(
                    package_name="DefaultPackage",
                    config=config,
                    repo_path=root,
                    remote_version="20260925185121",
                )

        update_resources.assert_awaited_once()
        extract_assets.assert_awaited_once_with(
            "newseer", "newseer/assetbundles/DefaultPackage/*", max_workers=1
        )


if __name__ == "__main__":
    unittest.main()
