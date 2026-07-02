import asyncio
import sys

import albi0
import httpx

from scripts._common import write_to_github_output
from scripts.seer_unity_assets.config import CONFIG, PET_ANIM_REPO, UNITY_ASSETS_REPO
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
