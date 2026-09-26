from contextlib import asynccontextmanager
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from scripts.seer_unity_assets.update import process_package


class AssetExtractionTests(unittest.IsolatedAsyncioTestCase):
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
