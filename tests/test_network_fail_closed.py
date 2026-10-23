import asyncio
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import httpx

from scripts.config_sources.update import download_data_async
from scripts._common import retry_call
from unittest.mock import Mock, AsyncMock


class NetworkBudgets(unittest.TestCase):
    def test_other_platform_success_is_not_committed_after_required_failure(self):
        from scripts.config_sources import update

        good, bad = Mock(), Mock()
        for name, platform in [("flash", good), ("unity", bad)]:
            platform.work_dir = Path(name)
            platform.get_local_version.return_value = "old"
            platform.get_remote_version.return_value = "new"
        good.get_configs = AsyncMock()
        bad.get_configs = AsyncMock(
            side_effect=RuntimeError("required download failed")
        )
        manager = Mock()
        with (
            patch.object(
                update,
                "build_live_platforms",
                return_value=[("flash", good), ("unity", bad)],
            ),
            patch.object(update.DataRepoManager, "from_checkout", return_value=manager),
            patch.object(update, "write_to_github_output"),
        ):
            with self.assertRaisesRegex(RuntimeError, "required download failed"):
                asyncio.run(update.run())
        manager.commit.assert_not_called()
        manager.push.assert_not_called()
        good.save_remote_version.assert_not_called()

    def test_http_failure_never_reports_download_success(self):
        for status, expected in ((404, 1), (408, 3), (429, 3), (503, 3)):
            calls = []

            async def handle(request):
                calls.append(1)
                return httpx.Response(status, request=request)

            with self.subTest(status=status), TemporaryDirectory() as directory:
                with patch(
                    "asyncio.sleep",
                    new=__import__("unittest.mock", fromlist=["AsyncMock"]).AsyncMock(),
                ):
                    with self.assertRaises(httpx.HTTPStatusError):
                        asyncio.run(
                            download_data_async(
                                [
                                    (
                                        httpx.URL("https://test.invalid"),
                                        Path("required.bytes"),
                                    )
                                ],
                                output_dir=Path(directory),
                                transport=httpx.MockTransport(handle),
                            )
                        )
                self.assertEqual(len(calls), expected)
                self.assertFalse(Path(directory, "required.bytes").exists())

    def test_three_total_not_four(self):
        calls = []

        def fail():
            calls.append(1)
            raise httpx.ConnectError("simulated")

        with patch("scripts._common.time.sleep"), self.assertRaises(httpx.ConnectError):
            retry_call(fail, max_attempts=3)
        self.assertEqual(len(calls), 3)
