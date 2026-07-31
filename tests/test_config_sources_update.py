from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from solaris.parse.base import BaseParser
from solaris.utils import change_workdir

from scripts.config_sources.update import (
    UNITY_PARSE_STATUS_FILE_NAME,
    build_live_platforms,
    parse_unity_configs_incrementally,
    publish_incremental_unity_outputs,
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

            results = parse_unity_configs_incrementally(
                [_WorkingParser, _BrokenParser],
                source_dir=source_dir,
                output_dir=output_dir,
                candidate_dir=candidate_dir,
            )
            publish_incremental_unity_outputs(
                results,
                candidate_dir=candidate_dir,
                output_dir=output_dir,
            )

            self.assertEqual(
                [(result.output_filename, result.status) for result in results],
                [("working.json", "updated"), ("broken.json", "retained_previous")],
            )
            self.assertEqual(
                json.loads((output_dir / "working.json").read_text(encoding="utf-8")),
                {"value": "new"},
            )
            self.assertEqual(
                json.loads((output_dir / "broken.json").read_text(encoding="utf-8")),
                {"value": "previous"},
            )
            status = json.loads(
                (output_dir / UNITY_PARSE_STATUS_FILE_NAME).read_text(encoding="utf-8")
            )
            self.assertEqual(status["retained_previous_outputs"][0]["output_filename"], "broken.json")

    def test_incremental_unity_parse_resolves_output_before_changing_directory(self) -> None:
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

            with change_workdir(root):
                results = parse_unity_configs_incrementally(
                    [_BrokenParser],
                    source_dir=Path("source"),
                    output_dir=Path("output"),
                    candidate_dir=Path("candidate"),
                )

            self.assertEqual(results[0].status, "retained_previous")

    def test_incremental_unity_parse_requires_a_previous_failed_output(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source_dir = root / "source"
            output_dir = root / "output"
            candidate_dir = root / "candidate"
            source_dir.mkdir()
            output_dir.mkdir()
            (source_dir / "broken.bytes").write_bytes(b"\xb4")

            with self.assertRaisesRegex(RuntimeError, "no previous broken.json"):
                parse_unity_configs_incrementally(
                    [_BrokenParser],
                    source_dir=source_dir,
                    output_dir=output_dir,
                    candidate_dir=candidate_dir,
                )


if __name__ == "__main__":
    unittest.main()
