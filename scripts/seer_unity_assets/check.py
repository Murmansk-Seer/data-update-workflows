import asyncio
import sys

import albi0
import httpx

from scripts._common import retry_call, write_to_github_output
from scripts.seer_unity_assets.config import CONFIG, PET_ANIM_REPO, UNITY_ASSETS_REPO
from scripts.seer_unity_assets.autocard_chips import (
    CHIP_ICON_MANIFEST,
    chip_icons_are_current,
)
from scripts.seer_unity_assets.partner_contracts import (
    PARTNER_CONTRACTS_REPO_PATH,
    is_partner_contracts_document_current,
)
from scripts.seer_unity_assets.update import get_manifest_path

REQUEST_TIMEOUT_SECONDS = 30.0
REQUEST_MAX_ATTEMPTS = 3
RETRYABLE_STATUS_CODES = frozenset((408, 429, *range(500, 600)))


def get_with_retry(url: str) -> httpx.Response:
    def request() -> httpx.Response:
        response = httpx.get(
            url, timeout=httpx.Timeout(REQUEST_TIMEOUT_SECONDS, connect=15.0)
        )
        if response.status_code in RETRYABLE_STATUS_CODES:
            response.raise_for_status()
        return response

    return retry_call(
        request,
        max_attempts=REQUEST_MAX_ATTEMPTS,
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
    if res.status_code == 404:
        return "0.0.0"
    res.raise_for_status()
    return res.json()["version"]


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


def has_current_chip_icons(repo_name: str, branch: str, package_version: str) -> bool:
    response = get_with_retry(
        f"https://raw.githubusercontent.com/{repo_name}/refs/heads/{branch}/{CHIP_ICON_MANIFEST}"
    )
    if response.status_code == 404:
        return False
    response.raise_for_status()
    try:
        return chip_icons_are_current(response.json(), package_version)
    except ValueError:
        return False


def config_source_is_current(version: str, branch: str) -> bool:
    base = f"https://raw.githubusercontent.com/Murmansk-Seer/config-sources/{branch}/unity/"
    response = get_with_retry(base + ".version")
    if response.status_code == 404:
        return False
    response.raise_for_status()
    if response.text.strip() != version:
        return False
    status = get_with_retry(base + ".parse-status.json")
    if status.status_code == 404:
        return True
    status.raise_for_status()
    return not status.json().get("retained_previous_outputs", [])


async def run(branch: str):
    albi0.load_all_plugins()

    need_update = False
    need_update_main = False
    need_update_pet = False
    official_config_version = None

    for package_name, config in CONFIG.items():
        target_repo = config.get("target_repo", UNITY_ASSETS_REPO)
        current_version = get_current_version(target_repo, branch, package_name)
        remote_version = await albi0.get_remote_version(config["updater_name"])
        if package_name == "ConfigPackage":
            official_config_version = remote_version
        write_to_github_output(f"{package_name}_version", remote_version)
        if current_version == remote_version:
            if package_name == "DefaultPackage" and not has_current_chip_icons(
                target_repo,
                branch,
                remote_version,
            ):
                print(
                    "DefaultPackage chip icons are missing or stale; requesting regeneration."
                )
                need_update = True
                need_update_main = True
                continue
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

    if official_config_version is None:
        raise RuntimeError("ConfigPackage version was not checked")
    need_update_config = not config_source_is_current(official_config_version, branch)
    write_to_github_output("need_update_config", str(need_update_config).lower())
    write_to_github_output(
        "need_update", "true" if need_update or need_update_config else "false"
    )
    write_to_github_output("need_update_main", "true" if need_update_main else "false")
    write_to_github_output("need_update_pet", "true" if need_update_pet else "false")


def main():
    branch = sys.argv[1] if len(sys.argv) > 1 else "main"
    asyncio.run(run(branch))
