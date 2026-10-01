"""Recover only the official chip bundle, independently of incremental manifests."""

import asyncio
import hashlib
from dataclasses import dataclass
from pathlib import Path
from pathlib import PurePosixPath
import re
import shutil
import tempfile
from urllib.parse import urlsplit

from albi0.plugins.newseer import NewseerManifestParser
from albi0 import RemoteManifestSnapshot
from albi0.update.version import LocalFileName, Manifest, ManifestItem
from albi0.log import logger
from albi0.utils import retryable
import anyio
from anyio.from_thread import start_blocking_portal
import httpx

from scripts.seer_unity_assets.autocard_chips import (
    CHIP_ICON_DIRECTORY,
    CHIP_ICON_MANIFEST,
    chip_icon_file_is_current,
    extract_chip_icons,
)

BASE_URL = "https://newseer.61.com/Assets/StandaloneWindows64/DefaultPackage/"
CHIP_BUNDLE_NAMES = frozenset({"game_ui_autocard", "game_ui_autocard.bundle"})
METADATA_ATTEMPT_SECONDS = 60
RESOURCE_ATTEMPT_SECONDS = 180


class ChipIntegrityError(httpx.HTTPError):
    """A complete response failed the official bundle size or MD5 check."""


def download_bytes(
    url: str,
    *,
    package_version: str = "",
    expected_size: int | None = None,
    expected_md5: str | None = None,
) -> bytes:
    """One request-level owner: read, deadline and integrity share three attempts."""
    resource = expected_size is not None
    if resource != (expected_md5 is not None):
        raise ValueError("Bundle downloads require both official size and MD5")
    stage = "chip_bundle" if resource else "chip_manifest"
    parts = urlsplit(url)
    safe_url = f"{parts.scheme}://{parts.hostname}{parts.path}"

    async def fetch():
        timeout = httpx.Timeout(180 if resource else 30, connect=15)
        deadline = RESOURCE_ATTEMPT_SECONDS if resource else METADATA_ATTEMPT_SECONDS
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            for attempt in range(1, 4):
                logger.info(
                    f"{stage} package=DefaultPackage version={package_version} "
                    f"url={safe_url} attempt={attempt}/3"
                )
                try:
                    with anyio.fail_after(deadline):
                        response = await client.get(url)
                        response.raise_for_status()
                        data = response.content
                        if resource and (
                            len(data) != expected_size
                            or hashlib.md5(data).hexdigest() != expected_md5
                        ):
                            raise ChipIntegrityError(
                                "Official chip bundle size/MD5 mismatch"
                            )
                        return data
                except (httpx.HTTPError, TimeoutError) as error:
                    status = (
                        error.response.status_code
                        if isinstance(error, httpx.HTTPStatusError)
                        else None
                    )
                    logger.warning(
                        f"{stage} version={package_version} url={safe_url} "
                        f"attempt={attempt}/3 error={type(error).__name__} status={status}"
                    )
                    if attempt == 3 or not retryable(error):
                        raise
                    await asyncio.sleep(attempt * 2)
        raise AssertionError("unreachable")

    with start_blocking_portal() as portal:
        return portal.call(fetch)


@dataclass(frozen=True)
class ChipBundle:
    name: str
    digest: str
    size: int
    url: str


def validate_chip_snapshot(
    snapshot: RemoteManifestSnapshot, package_version: str
) -> ChipBundle:
    if snapshot.version != package_version:
        raise ValueError(
            f"Chip manifest version mismatch: expected={package_version}, actual={snapshot.version}"
        )
    matches = [
        (key, item)
        for key, item in snapshot.items.items()
        if PurePosixPath(str(key).replace("\\", "/")).name in CHIP_BUNDLE_NAMES
    ]
    if len(matches) != 1:
        raise ValueError("Official manifest must contain exactly one autocard bundle")
    key, item = matches[0]
    digest = item.file_hash.decode("ascii").lower()
    if (
        not re.fullmatch(r"[0-9a-f]{32}", digest)
        or type(item.file_size) is not int
        or item.file_size <= 0
    ):
        raise ValueError("Invalid official chip bundle hash/size")
    if item.remote_filename != BASE_URL + digest:
        raise ValueError("Chip bundle URL does not match the official content hash")
    return ChipBundle(
        PurePosixPath(str(key).replace("\\", "/")).name,
        digest,
        item.file_size,
        item.remote_filename,
    )


def fetch_chip_snapshot(package_version: str) -> RemoteManifestSnapshot:
    url = f"{BASE_URL}PackageManifest_DefaultPackage_{package_version}.bytes"
    raw = download_bytes(url, package_version=package_version)
    manifest = NewseerManifestParser()(raw)
    if (
        manifest["PackageName"] != "DefaultPackage"
        or manifest["PackageVersion"] != package_version
    ):
        raise ValueError("Official chip manifest version/package mismatch")
    bundles = manifest["BundleList"]
    for count, items in (
        ("PackageBundleCount", "BundleList"),
        ("PackageAssetCount", "PackageAssetInfos"),
    ):
        if (
            type(manifest[count]) is not int
            or manifest[count] < 0
            or manifest[count] != len(manifest[items])
        ):
            raise ValueError("Invalid official chip manifest structure")
    if len({item["BundleName"] for item in bundles}) != len(bundles):
        raise ValueError("Duplicate official bundle names")
    full = Manifest(
        package_version,
        {
            LocalFileName(
                "newseer/assetbundles/DefaultPackage/" + item["BundleName"]
            ): ManifestItem(
                BASE_URL + item["FileHash"].lower(),
                item["BundleName"] + ".bundle",
                item["FileHash"].encode("ascii"),
                item["FileSize"],
            )
            for item in bundles
        },
    )
    return RemoteManifestSnapshot.from_manifest(full)


def bundle_is_valid(path: Path, size: int, digest: str) -> bool:
    try:
        return (
            path.stat().st_size == size
            and hashlib.md5(path.read_bytes()).hexdigest() == digest
        )
    except OSError:
        return False


def recover_chip_icons(
    root: Path,
    package_version: str,
    *,
    manifest_snapshot: RemoteManifestSnapshot | None = None,
) -> None:
    if not re.fullmatch(r"[0-9]{14}", package_version):
        raise ValueError("Invalid DefaultPackage version")
    spec = (
        validate_chip_snapshot(manifest_snapshot, package_version)
        if manifest_snapshot is not None
        else None
    )
    if chip_icon_file_is_current(root, package_version):
        logger.info(f"chip_cache version={package_version} valid; no recovery download")
        return
    if spec is None:
        logger.info(f"chip_manifest version={package_version} source=official_download")
        spec = validate_chip_snapshot(
            fetch_chip_snapshot(package_version), package_version
        )
    else:
        logger.info(
            f"chip_manifest version={package_version} source=albi0_current_run; reused full snapshot"
        )
    digest, size = spec.digest, spec.size
    bundle_root = root / "newseer/assetbundles/DefaultPackage"
    local = next(
        (
            path
            for name in ("game_ui_autocard", "game_ui_autocard.bundle")
            if bundle_is_valid(path := bundle_root / name, size, digest)
        ),
        None,
    )
    if local is not None:
        logger.info(
            f"chip_bundle version={package_version} reused size={size} md5={digest}"
        )
    # An isolated candidate avoids trusting the downloader's old resource list,
    # and no published image or manifest is touched until extraction validates.
    with tempfile.TemporaryDirectory(prefix="autocard-chip-recovery-") as directory:
        candidate = Path(directory)
        if local is None:
            local = candidate / "game_ui_autocard"
            local.write_bytes(
                download_bytes(
                    spec.url,
                    package_version=package_version,
                    expected_size=size,
                    expected_md5=digest,
                )
            )
            if not bundle_is_valid(local, size, digest):
                raise ValueError("Official chip bundle size/hash mismatch")
        logger.info(
            f"chip_extract version={package_version} source={local.name} md5={digest}"
        )
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
        logger.info(
            f"chip_published version={package_version} icons={count} size={size} md5={digest}"
        )


async def ensure_chip_icons(
    root: Path,
    package_version: str,
    *,
    manifest_snapshot: RemoteManifestSnapshot | None = None,
) -> None:
    await asyncio.to_thread(
        recover_chip_icons, root, package_version, manifest_snapshot=manifest_snapshot
    )
