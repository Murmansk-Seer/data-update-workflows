"""Recover only the official chip bundle, independently of incremental manifests."""

import asyncio
import hashlib
from pathlib import Path
import re
import shutil
import tempfile
import time

from albi0.plugins.newseer import NewseerManifestParser
import httpx

from scripts.seer_unity_assets.autocard_chips import (
    CHIP_ICON_DIRECTORY,
    CHIP_ICON_MANIFEST,
    chip_icon_file_is_current,
    extract_chip_icons,
)

BASE_URL = "https://newseer.61.com/Assets/StandaloneWindows64/DefaultPackage/"


def download_bytes(url: str) -> bytes:
    """Three total attempts; never wrap a downloader that already retries."""
    for attempt in range(1, 4):
        try:
            response = httpx.get(url, timeout=httpx.Timeout(180, connect=15))
            response.raise_for_status()
            return response.content
        except httpx.HTTPError:
            if attempt == 3:
                raise
            time.sleep(attempt * 2)
    raise AssertionError("unreachable")


def bundle_is_valid(path: Path, size: int, digest: str) -> bool:
    try:
        return (
            path.stat().st_size == size
            and hashlib.md5(path.read_bytes()).hexdigest() == digest
        )
    except OSError:
        return False


def recover_chip_icons(root: Path, package_version: str) -> None:
    if chip_icon_file_is_current(root, package_version):
        print("Official autocard chip cache is valid; no recovery download.")
        return
    if not re.fullmatch(r"[0-9]{14}", package_version):
        raise ValueError("Invalid DefaultPackage version")
    raw_manifest = download_bytes(
        f"{BASE_URL}PackageManifest_DefaultPackage_{package_version}.bytes"
    )
    manifest = NewseerManifestParser()(raw_manifest)
    if (
        manifest["PackageVersion"] != package_version
        or manifest["PackageName"] != "DefaultPackage"
    ):
        raise ValueError("Official chip manifest version/package mismatch")
    bundles = [
        item
        for item in manifest["BundleList"]
        if item["BundleName"] in {"game_ui_autocard", "game_ui_autocard.bundle"}
    ]
    if len(bundles) != 1:
        raise ValueError("Official manifest must contain exactly one autocard bundle")
    item = bundles[0]
    digest, size = item["FileHash"].lower(), item["FileSize"]
    if not re.fullmatch(r"[0-9a-f]{32}", digest) or type(size) is not int or size <= 0:
        raise ValueError("Invalid official chip bundle hash/size")
    bundle_root = root / "newseer/assetbundles/DefaultPackage"
    local = next(
        (
            path
            for name in ("game_ui_autocard", "game_ui_autocard.bundle")
            if bundle_is_valid(path := bundle_root / name, size, digest)
        ),
        None,
    )
    # An isolated candidate avoids trusting the downloader's old resource list,
    # and no published image or manifest is touched until extraction validates.
    with tempfile.TemporaryDirectory(prefix="autocard-chip-recovery-") as directory:
        candidate = Path(directory)
        if local is None:
            local = candidate / "game_ui_autocard"
            local.write_bytes(download_bytes(f"{BASE_URL}{digest}"))
            if not bundle_is_valid(local, size, digest):
                raise ValueError("Official chip bundle size/hash mismatch")
        count = extract_chip_icons(local, candidate, package_version)
        if not chip_icon_file_is_current(candidate, package_version):
            raise ValueError("Recovered chip icons failed PNG/manifest validation")
        destination = root / CHIP_ICON_DIRECTORY
        destination.mkdir(parents=True, exist_ok=True)
        for image in (candidate / CHIP_ICON_DIRECTORY).glob("autocardChip_*.png"):
            shutil.copyfile(image, destination / image.name)
        manifest_path = root / CHIP_ICON_MANIFEST
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(candidate / CHIP_ICON_MANIFEST, manifest_path)
        print(f"Official autocard chip icons recovered: {count}; bundle MD5: {digest}")


async def ensure_chip_icons(root: Path, package_version: str) -> None:
    await asyncio.to_thread(recover_chip_icons, root, package_version)
