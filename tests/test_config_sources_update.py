from __future__ import annotations

import json
import asyncio
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch
from scripts.config_sources import update

from solaris.parse.base import BaseParser
from solaris.utils import change_workdir

from scripts.config_sources.update import (
    CLOTH_POS_DEST_FILENAME,
    CLOTH_POS_RAW_URL,
    UNITY_PARSE_STATUS_FILE_NAME,
    Unity,
    build_live_platforms,
    parse_unity_configs_incrementally,
)


class _WorkingParser(BaseParser[dict[str, str]]):
    @classmethod
    def source_config_filename(cls) -> str:
        return "working.bytes"

    @classmethod
    def parsed_config_filename(cls) -> str:
        return "working.json"

    def parse(self, data: bytes) -> dict[str, str]:
        return {"value": data.decode("utf-8")}


class _BrokenParser(BaseParser[dict[str, str]]):
    @classmethod
    def source_config_filename(cls) -> str:
        return "broken.bytes"

    @classmethod
    def parsed_config_filename(cls) -> str:
        return "broken.json"

    def parse(self, data: bytes) -> dict[str, str]:
        raise UnicodeDecodeError("utf-8", data, 0, 1, "invalid test input")


class ConfigSourcesUpdateTests(unittest.TestCase):
    def test_shared_snapshot_is_deferred_until_commit_gate(self):
        version, revision = "20261113190033", "a" * 40
        with TemporaryDirectory() as directory:
            platform = Unity(Path(directory) / "unity")
            platform.get_remote_version = Mock(return_value=version)

            async def download(tasks, *, output_dir):
                (output_dir / "working.bytes").write_bytes(b"new")
                contract = output_dir / "_derived" / "partner_contracts.json"
                contract.parent.mkdir(exist_ok=True)
                contract.write_text(
                    json.dumps(
                        {
                            "schema_version": 1,
                            "source": {"config_package_version": version},
                        }
                    )
                )

            with (
                patch.object(
                    update, "get_installed_parser_revision", return_value=revision
                ),
                patch.object(update, "build_client"),
                patch.object(update, "collect_directory_tasks", return_value=[]),
                patch.object(update, "download_data_async", side_effect=download),
                patch.object(
                    update, "required_unity_sources", return_value={"working.bytes"}
                ),
                patch.object(
                    update, "parse_unity_snapshot", return_value={"working.json": {}}
                ) as parse_snapshot,
                patch.object(update, "publish_unity_snapshot") as publish,
                patch.object(platform, "_get_cloth_pos", return_value=b"{}"),
            ):
                asyncio.run(platform.get_configs())
                parse_snapshot.assert_called_once_with({"working.bytes": b"new"})
                publish.assert_not_called()
                self.assertFalse(platform.version_file_path.exists())
                platform.save_remote_version(version)
                publish.assert_called_once()
                self.assertEqual(publish.call_args.kwargs["version"], version)
                self.assertEqual(publish.call_args.kwargs["parser_revision"], revision)
                self.assertEqual(
                    set(publish.call_args.kwargs["extra_files"]),
                    {"partner_contracts.json", "clothPos.json"},
                )

    @patch("scripts.config_sources.update.retry_call")
    def test_unity_imports_published_cloth_positions(self, retry_call: Mock) -> None:
        payload = b'{"position": "preview"}\n'
        response = Mock(content=payload)
        retry_call.return_value = response

        with TemporaryDirectory() as temporary_directory:
            Unity(Path(temporary_directory))._import_cloth_pos()
            self.assertEqual(
                (Path(temporary_directory) / CLOTH_POS_DEST_FILENAME).read_bytes(),
                payload,
            )

        self.assertEqual(retry_call.call_args.kwargs["url"], CLOTH_POS_RAW_URL)
        response.raise_for_status.assert_called_once_with()

    def test_live_platforms_exclude_frozen_html5_snapshot(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            platforms = build_live_platforms(Path(temporary_directory))

        self.assertEqual([name for name, _ in platforms], ["flash", "unity"])

    def test_incremental_unity_parse_retains_previous_failed_output(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source_dir = root / "source"
            output_dir = root / "output"
            candidate_dir = root / "candidate"
            source_dir.mkdir()
            output_dir.mkdir()
            (source_dir / "working.bytes").write_text("new", encoding="utf-8")
            (source_dir / "broken.bytes").write_bytes(b"\xb4")
            (output_dir / "broken.json").write_text(
                '{"value": "previous"}\n', encoding="utf-8"
            )

            with self.assertRaisesRegex(RuntimeError, "refusing to publish stale"):
                parse_unity_configs_incrementally(
                    [_WorkingParser, _BrokenParser],
                    source_dir=source_dir,
                    output_dir=output_dir,
                    candidate_dir=candidate_dir,
                )
            self.assertFalse((output_dir / "working.json").exists())
            self.assertEqual(
                json.loads((output_dir / "broken.json").read_text(encoding="utf-8")),
                {"value": "previous"},
            )
            self.assertFalse((output_dir / UNITY_PARSE_STATUS_FILE_NAME).exists())

    def test_incremental_unity_parse_resolves_output_before_changing_directory(
        self,
    ) -> None:
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source_dir = root / "source"
            output_dir = root / "output"
            source_dir.mkdir()
            output_dir.mkdir()
            (source_dir / "broken.bytes").write_bytes(b"\xb4")
            (output_dir / "broken.json").write_text(
                '{"value": "previous"}\n', encoding="utf-8"
            )

            with (
                change_workdir(root),
                self.assertRaisesRegex(RuntimeError, "refusing to publish stale"),
            ):
                parse_unity_configs_incrementally(
                    [_BrokenParser],
                    source_dir=Path("source"),
                    output_dir=Path("output"),
                    candidate_dir=Path("candidate"),
                )

    def test_incremental_unity_parse_requires_a_previous_failed_output(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source_dir = root / "source"
            output_dir = root / "output"
            candidate_dir = root / "candidate"
            source_dir.mkdir()
            output_dir.mkdir()
            (source_dir / "broken.bytes").write_bytes(b"\xb4")

            with self.assertRaisesRegex(
                RuntimeError, "refusing to publish stale broken.json"
            ):
                parse_unity_configs_incrementally(
                    [_BrokenParser],
                    source_dir=source_dir,
                    output_dir=output_dir,
                    candidate_dir=candidate_dir,
                )


if __name__ == "__main__":
    unittest.main()
