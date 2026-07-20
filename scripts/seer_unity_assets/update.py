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
from scripts.seer_unity_assets.partner_contracts import (
    PARTNER_CONTRACTS_REPO_PATH,
    extract_partner_contracts,
    partner_contracts_file_is_current,
)


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
) -> None:
    async with albi0.session():
        await albi0.update_resources(
            config["updater_name"],
            *config["update_args"],
            manifest_path=get_manifest_path(package_name),
            timeout=60.0,
            ignore_version=force,
            min_size=config.get("min_size"),
            max_size=config.get("max_size"),
        )
        if not config.get("skip_extract"):
            await albi0.extract_assets(
                config["extractor_name"],
                get_bundle_path(package_name),
                max_workers=2,
            )
    if package_name == "ConfigPackage":
        changed = extract_partner_contracts(
            bundle_paths=get_bundle_directory(repo_path, package_name).glob("**/*"),
            config_package_version=remote_version,
            output_path=repo_path / PARTNER_CONTRACTS_REPO_PATH,
        )
        status = "updated" if changed else "already current"
        print(f"Official partner contracts {status}.")


def parse_args() -> tuple[bool, str, set[str] | None]:
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

    return force, repo_path, packages


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
):
    albi0.load_all_plugins()

    manager = DataRepoManager.from_checkout(repo_path)
    has_update = False

    for package_name, config in CONFIG.items():
        if packages is not None and package_name not in packages:
            continue

        remote_version = await albi0.get_remote_version(config["updater_name"])
        package_force = force
        if package_name == "ConfigPackage":
            package_force = package_force or not partner_contracts_file_is_current(
                Path(repo_path) / PARTNER_CONTRACTS_REPO_PATH,
                config_package_version=remote_version,
            )
        print(f"⚙️ 正在更新资源包 {package_name}...")
        await process_package(
            package_name=package_name,
            config=config,
            repo_path=Path(repo_path),
            remote_version=remote_version,
            force=package_force,
        )
        print(f"✅ 资源包 {package_name} 更新完成")
        if not manager.commit(
            f"{package_name}: Update to {remote_version} | Time: {get_current_time_str()}",
            files=get_push_patterns(package_name, config),
        ):
            continue
        if not manager.push():
            raise RuntimeError(f"{package_name} 更新已提交，但推送远端失败")
        has_update = True

    write_to_github_output("has_update", "true" if has_update else "false")


def main():
    force, repo_path, packages = parse_args()
    asyncio.run(run(force=force, repo_path=repo_path, packages=packages))
