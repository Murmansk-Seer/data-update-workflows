import asyncio
import sys
from pathlib import Path

import albi0

from scripts._common import (
    DataRepoManager,
    get_current_time_str,
    write_to_github_output,
)
from scripts.seer_unity_assets.config import CONFIG, PackageConfig
from scripts.seer_unity_assets.autocard_chips import (
    CHIP_ICON_DIRECTORY,
    CHIP_ICON_MANIFEST,
    chip_icon_file_is_current,
    is_chip_bundle,
)
from scripts.seer_unity_assets.chip_recovery import ensure_chip_icons
from scripts.seer_unity_assets.partner_contracts import (
    PARTNER_CONTRACTS_REPO_PATH,
    extract_partner_contracts,
    partner_contracts_file_is_current,
)
from scripts.seer_unity_assets.png_validation import validate_changed_pngs


def get_manifest_path(package_name: str) -> str:
    return f"package-manifests/{package_name}.json"


def get_bundle_path(package_name: str) -> str:
    return f"newseer/assetbundles/{package_name}/*"


def get_bundle_directory(repo_path: Path, package_name: str) -> Path:
    return repo_path / "newseer" / "assetbundles" / package_name


async def process_package(
    *,
    package_name: str,
    config: PackageConfig,
    repo_path: Path,
    remote_version: str,
    force: bool = False,
    chip_icons_only: bool = False,
) -> None:
    if chip_icons_only:
        await ensure_chip_icons(repo_path, remote_version)
        return
    async with albi0.session():
        await albi0.update_resources(
            config["updater_name"],
            *(
                ["game_ui_autocard.bundle"]
                if chip_icons_only
                else config["update_args"]
            ),
            manifest_path=(
                ".cache/autocard-chip-package.json"
                if chip_icons_only
                else get_manifest_path(package_name)
            ),
            timeout=180.0,
            ignore_version=force,
            min_size=config.get("min_size"),
            max_size=config.get("max_size"),
        )
        bundle_directory = get_bundle_directory(repo_path, package_name)
        has_bundle_files = bundle_directory.is_dir() and any(
            path.is_file() for path in bundle_directory.glob("**/*")
        )
        if not config.get("skip_extract") and has_bundle_files:
            chip_bundles = [
                path for path in bundle_directory.iterdir() if is_chip_bundle(path)
            ]
            patterns = (
                [
                    str(path)
                    for path in bundle_directory.iterdir()
                    if path.is_file() and not is_chip_bundle(path)
                ]
                if chip_bundles
                else [get_bundle_path(package_name)]
            )
            if chip_icons_only:
                patterns = []
            # Unity bundles may expose one image as both Sprite and Texture2D.
            # albi0 writes both to the same PNG path, so parallel exports can
            # interleave bytes and produce a file with invalid chunk CRCs.
            if patterns:
                await albi0.extract_assets(
                    config["extractor_name"],
                    *patterns,
                    max_workers=1,
                )
        elif not config.get("skip_extract"):
            print(
                f"No transient {package_name} bundles found; "
                "using the committed extracted assets."
            )
        if (
            package_name == "DefaultPackage"
            and "game_ui_autocard.bundle" in config["update_args"]
            and not chip_icon_file_is_current(repo_path, remote_version)
        ):
            await ensure_chip_icons(repo_path, remote_version)
    if package_name == "ConfigPackage":
        changed = extract_partner_contracts(
            asset_root=repo_path / "newseer",
            config_package_version=remote_version,
            output_path=repo_path / PARTNER_CONTRACTS_REPO_PATH,
        )
        status = "updated" if changed else "already current"
        print(f"Official partner contracts {status}.")


def parse_args() -> tuple[bool, str, set[str] | None, bool]:
    force = "--force" in sys.argv
    repo_path = "."
    packages: set[str] | None = None

    if "--repo-path" in sys.argv:
        repo_path = sys.argv[sys.argv.index("--repo-path") + 1]

    if "--packages" in sys.argv:
        packages = {
            name.strip()
            for name in sys.argv[sys.argv.index("--packages") + 1].split(",")
            if name.strip()
        }

    return force, repo_path, packages, "--chip-icons-only" in sys.argv


def get_push_patterns(package_name: str, config: PackageConfig) -> list[str]:
    if push_patterns := config.get("push_patterns"):
        return push_patterns

    files_fp = (
        f"{config['extractor_name']}/assets/"
        if config.get("extractor_name") and not config.get("skip_extract")
        else get_bundle_path(package_name)
    )
    return ["package-manifests/", files_fp]


async def run(
    *,
    force: bool = False,
    repo_path: str = ".",
    packages: set[str] | None = None,
    chip_icons_only: bool = False,
):
    albi0.load_all_plugins()

    manager = DataRepoManager.from_checkout(repo_path)
    has_update = False

    for package_name, config in CONFIG.items():
        if chip_icons_only and package_name != "DefaultPackage":
            continue
        if packages is not None and package_name not in packages:
            continue

        remote_version = await albi0.get_remote_version(config["updater_name"])
        package_force = force or chip_icons_only
        if package_name == "ConfigPackage":
            package_force = package_force or not partner_contracts_file_is_current(
                Path(repo_path) / PARTNER_CONTRACTS_REPO_PATH,
                config_package_version=remote_version,
            )
        if package_name == "DefaultPackage":
            package_force = package_force or not chip_icon_file_is_current(
                Path(repo_path),
                remote_version,
            )
        print(f"⚙️ 正在更新资源包 {package_name}...")
        await process_package(
            package_name=package_name,
            config=config,
            repo_path=Path(repo_path),
            remote_version=remote_version,
            force=package_force,
            chip_icons_only=chip_icons_only,
        )
        print(f"✅ 资源包 {package_name} 更新完成")
        if not config.get("skip_extract"):
            validate_changed_pngs(Path(repo_path), manager.get_changed_files())
        if not manager.commit(
            f"{package_name}: Update to {remote_version} | Time: {get_current_time_str()}",
            files=(
                [CHIP_ICON_DIRECTORY, CHIP_ICON_MANIFEST]
                if chip_icons_only
                else get_push_patterns(package_name, config)
            ),
        ):
            continue
        if not manager.push():
            raise RuntimeError(f"{package_name} 更新已提交，但推送远端失败")
        has_update = True

    write_to_github_output("has_update", "true" if has_update else "false")


def main():
    force, repo_path, packages, chip_icons_only = parse_args()
    asyncio.run(
        run(
            force=force,
            repo_path=repo_path,
            packages=packages,
            chip_icons_only=chip_icons_only,
        )
    )
