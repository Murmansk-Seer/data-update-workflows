import asyncio
import sys

import albi0
import httpx

from scripts._common import retry_call, write_to_github_output
from scripts.seer_unity_assets.config import CONFIG, PET_ANIM_REPO, UNITY_ASSETS_REPO
from scripts.seer_unity_assets.partner_contracts import (
    PARTNER_CONTRACTS_REPO_PATH,
    is_partner_contracts_document_current,
)
from scripts.seer_unity_assets.update import get_manifest_path

REQUEST_TIMEOUT_SECONDS = 30.0
REQUEST_MAX_RETRIES = 3
RETRYABLE_STATUS_CODES = frozenset((408, 429, 500, 502, 503, 504))


def get_with_retry(url: str) -> httpx.Response:
    def request() -> httpx.Response:
        response = httpx.get(url, timeout=REQUEST_TIMEOUT_SECONDS)
        if response.status_code in RETRYABLE_STATUS_CODES:
            response.raise_for_status()
        return response

    return retry_call(
        request,
        max_retries=REQUEST_MAX_RETRIES,
        base_delay=1.0,
        max_delay=4.0,
    )


def get_current_version(
    repo_name: str,
    branch: str,
    package_name: str,
) -> str:
    res = get_with_retry(
        "https://raw.githubusercontent.com/"
        f"{repo_name}/refs/heads/{branch}/{get_manifest_path(package_name)}"
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
    response = get_with_retry(
        "https://raw.githubusercontent.com/"
        f"{repo_name}/refs/heads/{branch}/{PARTNER_CONTRACTS_REPO_PATH}"
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
    need_update_pet = False

    for package_name, config in CONFIG.items():
        target_repo = config.get("target_repo", UNITY_ASSETS_REPO)
        current_version = get_current_version(target_repo, branch, package_name)
        remote_version = await albi0.get_remote_version(config["updater_name"])
        if current_version == remote_version:
            if package_name == "ConfigPackage" and not has_current_partner_contracts(
                target_repo,
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
            print(f"📦 {package_name} 已是最新版本 ({target_repo})")
            continue

        print(
            f"🔄 {package_name} 需要更新 ({target_repo})，"
            f"当前版本：{current_version}，远程版本：{remote_version}"
        )
        need_update = True
        if target_repo == PET_ANIM_REPO:
            need_update_pet = True
        else:
            need_update_main = True

    write_to_github_output("need_update", "true" if need_update else "false")
    write_to_github_output("need_update_main", "true" if need_update_main else "false")
    write_to_github_output("need_update_pet", "true" if need_update_pet else "false")


def main():
    branch = sys.argv[1] if len(sys.argv) > 1 else "main"
    asyncio.run(run(branch))
