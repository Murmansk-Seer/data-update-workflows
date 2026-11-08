from __future__ import annotations

import asyncio
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import AsyncMock, Mock, patch

from scripts.config_sources import update


REVISION = "b" * 40
PREVIOUS = "a" * 40
VERSION = "20261106181039"


class ParserRevisionTests(unittest.TestCase):
    def _receipts(self, revisions=(REVISION, REVISION)):
        return [
            Mock(
                read_text=Mock(
                    return_value=json.dumps(
                        {"vcs_info": {"vcs": "git", "commit_id": rev}}
                    )
                )
            )
            for rev in revisions
        ]

    def test_requires_identical_immutable_package_receipts(self):
        with patch.object(update, "distribution", side_effect=self._receipts()):
            self.assertEqual(update.get_installed_parser_revision(), REVISION)

    def test_rejects_mixed_package_sources(self):
        with patch.object(
            update, "distribution", side_effect=self._receipts((REVISION, PREVIOUS))
        ):
            with self.assertRaisesRegex(RuntimeError, "same Git commit"):
                update.get_installed_parser_revision()

    def test_rejects_missing_malformed_and_unpinned_sources(self):
        for receipt in [
            None,
            "invalid",
            "[]",
            "{}",
            '{"vcs_info": null}',
            json.dumps({"vcs_info": {"vcs": "git", "commit_id": "main"}}),
            json.dumps({"vcs_info": {"vcs": "hg", "commit_id": REVISION}}),
        ]:
            with (
                self.subTest(receipt=receipt),
                patch.object(
                    update,
                    "distribution",
                    return_value=Mock(read_text=Mock(return_value=receipt)),
                ),
            ):
                with self.assertRaises(RuntimeError):
                    update.get_installed_parser_revision()

    def _run(
        self,
        *,
        marker: str | None = PREVIOUS,
        force=False,
        fail=False,
        other_fail=False,
        installed: str | Exception = REVISION,
        missing_table=False,
    ):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            platform = update.Unity(root / "unity")
            platform.version_file_path.write_text(VERSION)
            if marker is not None:
                (platform.work_dir / update.UNITY_PARSER_REVISION_FILE_NAME).write_text(
                    marker
                )
            (platform.work_dir / update.SOMUA_VERSION_FILE_NAME).write_text(VERSION)
            for name in update.SOMUA_RESOURCES:
                (platform.work_dir / name).write_text('{"data": []}')
            if missing_table:
                (platform.work_dir / next(iter(update.SOMUA_RESOURCES))).unlink()
            platform.get_remote_version = Mock(return_value=VERSION)
            platform.get_configs = AsyncMock(
                side_effect=RuntimeError("bad parser") if fail else None
            )
            platforms = [("unity", platform)]
            if other_fail:
                other = update.Unity(root / "other")
                other.get_remote_version = Mock(
                    side_effect=RuntimeError("other platform failed")
                )
                platforms.append(("other", other))
            manager = Mock()
            manager.commit.return_value = True
            manager.push.return_value = True
            with (
                patch.object(
                    update,
                    "get_installed_parser_revision",
                    side_effect=installed if isinstance(installed, Exception) else None,
                    return_value=installed,
                ),
                patch.object(update, "build_live_platforms", return_value=platforms),
                patch.object(
                    update.DataRepoManager, "from_checkout", return_value=manager
                ),
                patch.object(update, "write_to_github_output"),
            ):
                if fail or other_fail or isinstance(installed, Exception):
                    with self.assertRaises(RuntimeError):
                        asyncio.run(update.run(force=force))
                    manager.commit.assert_not_called()
                    manager.push.assert_not_called()
                    self.assertEqual(
                        (
                            platform.work_dir / update.UNITY_PARSER_REVISION_FILE_NAME
                        ).read_text()
                        if marker
                        else None,
                        marker,
                    )
                else:
                    asyncio.run(update.run(force=force))
                return (
                    platform.get_configs.await_count,
                    manager.commit.call_count,
                    (
                        platform.work_dir / update.UNITY_PARSER_REVISION_FILE_NAME
                    ).read_text()
                    if (
                        platform.work_dir / update.UNITY_PARSER_REVISION_FILE_NAME
                    ).exists()
                    else None,
                )

    def test_same_official_version_new_parser_reexports(self):
        self.assertEqual(self._run(), (1, 1, REVISION + "\n"))

    def test_migration_reexports_once_and_then_is_noop(self):
        old = "bb29e761b498c3307d756f941b43ee9613385341"
        new = "e32336876474d80fef625b60004f304366175cf0"
        with patch.object(update, "distribution", side_effect=self._receipts((new, new))):
            self.assertEqual(update.get_installed_parser_revision(), new)
        self.assertEqual(self._run(marker=old, installed=new), (1, 1, new + "\n"))
        self.assertEqual(self._run(marker=new, installed=new), (0, 0, new))

    def test_missing_parser_marker_reexports(self):
        self.assertEqual(self._run(marker=None), (1, 1, REVISION + "\n"))

    def test_same_version_and_parser_is_noop(self):
        self.assertEqual(self._run(marker=REVISION), (0, 0, REVISION))

    def test_force_reexports_same_parser(self):
        self.assertEqual(
            self._run(marker=REVISION, force=True), (1, 1, REVISION + "\n")
        )

    def test_missing_required_table_reexports(self):
        self.assertEqual(
            self._run(marker=REVISION, missing_table=True), (1, 1, REVISION + "\n")
        )

    def test_parse_failure_never_advances_marker_or_commits(self):
        self._run(fail=True)

    def test_other_platform_failure_never_advances_marker_or_commits(self):
        self._run(other_fail=True)

    def test_invalid_package_receipt_blocks_even_forced_refresh(self):
        self.assertEqual(
            self._run(force=True, installed=RuntimeError("invalid receipt"))[0], 0
        )


if __name__ == "__main__":
    unittest.main()
