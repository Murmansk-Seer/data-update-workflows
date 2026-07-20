from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from scripts.config_sources.update import build_live_platforms


class ConfigSourcesUpdateTests(unittest.TestCase):
    def test_live_platforms_exclude_frozen_html5_snapshot(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            platforms = build_live_platforms(Path(temporary_directory))

        self.assertEqual([name for name, _ in platforms], ["flash", "unity"])


if __name__ == "__main__":
    unittest.main()
