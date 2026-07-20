import asyncio
import sys

import albi0
import httpx

from scripts._common import write_to_github_output
from scripts.seer_unity_assets.config import CONFIG, UNITY_ASSETS_REPO
from scripts.seer_unity_assets.partner_contracts import (
    PARTNER_CONTRACTS_REPO_PATH,
    is_partner_contracts_document_current,
)
from scripts.seer_unity_assets.update import get_manifest_path


def get_current_version(
    repo_name: str,
    branch: str,
    package_name: str,
) -> str:
    res = httpx.get(
        f"https://raw.githubusercontent.com/{repo_name}/refs/heads/{branch}/{get_manifest_path(package_name)}"
    )
    try:
        res.raise_for_status()
        return res.json()["version"]
    except httpx.HTTPStatusError:
        return "0.0.0"


def has_current_partner_contracts(
    repo_name: str,
    branch: str,
    config_package_version: str,
) -> bool:
    response = httpx.get(
        "https://raw.githubusercontent.com/"
        f"{repo_name}/refs/heads/{branch}/{PARTNER_CONTRACTS_REPO_PATH}",
        timeout=30.0,
    )
    if response.status_code == 404:
        return False
    response.raise_for_status()
    try:
        document = response.json()
    except ValueError:
        return False
    return is_partner_contracts_document_current(
        document,
        config_package_version=config_package_version,
    )


async def run(branch: str):
    albi0.load_all_plugins()

    need_update = False
    need_update_main = False

    for package_name, config in CONFIG.items():
        current_version = get_current_version(UNITY_ASSETS_REPO, branch, package_name)
        remote_version = await albi0.get_remote_version(config["updater_name"])
        if current_version == remote_version:
            if package_name == "ConfigPackage" and not has_current_partner_contracts(
                UNITY_ASSETS_REPO,
                branch,
                remote_version,
            ):
                print(
                    "ConfigPackage partner contracts are missing or stale; "
                    "requesting a one-time regeneration."
                )
                need_update = True
                need_update_main = True
                continue
            print(f"📦 {package_name} 已是最新版本 ({UNITY_ASSETS_REPO})")
            continue

        print(
            f"🔄 {package_name} 需要更新 ({UNITY_ASSETS_REPO})，"
            f"当前版本：{current_version}，远程版本：{remote_version}"
        )
        need_update = True
        need_update_main = True

    write_to_github_output("need_update", "true" if need_update else "false")
    write_to_github_output("need_update_main", "true" if need_update_main else "false")


def main():
    branch = sys.argv[1] if len(sys.argv) > 1 else "main"
    asyncio.run(run(branch))
