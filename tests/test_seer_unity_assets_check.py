from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

import httpx

from scripts.seer_unity_assets.check import get_current_version


class SeerUnityAssetsCheckTests(unittest.TestCase):
    @patch("scripts._common.time.sleep")
    @patch("scripts.seer_unity_assets.check.httpx.get")
    def test_current_version_retries_read_timeout(
        self,
        get: Mock,
        sleep: Mock,
    ) -> None:
        request = httpx.Request("GET", "https://raw.githubusercontent.com/test")
        get.side_effect = [
            httpx.ReadTimeout("temporary timeout"),
            httpx.Response(
                200,
                request=request,
                json={"version": "1.2.3"},
            ),
        ]

        version = get_current_version("owner/repo", "main", "ConfigPackage")

        self.assertEqual(version, "1.2.3")
        self.assertEqual(get.call_count, 2)
        sleep.assert_called_once_with(1.0)

    @patch("scripts._common.time.sleep")
    @patch("scripts.seer_unity_assets.check.httpx.get")
    def test_current_version_retries_transient_server_error(
        self,
        get: Mock,
        sleep: Mock,
    ) -> None:
        request = httpx.Request("GET", "https://raw.githubusercontent.com/test")
        get.side_effect = [
            httpx.Response(503, request=request),
            httpx.Response(
                200,
                request=request,
                json={"version": "2.0.0"},
            ),
        ]

        version = get_current_version("owner/repo", "main", "ConfigPackage")

        self.assertEqual(version, "2.0.0")
        self.assertEqual(get.call_count, 2)
        sleep.assert_called_once_with(1.0)

    @patch("scripts.seer_unity_assets.check.httpx.get")
    def test_missing_version_file_is_not_retried(
        self,
        get: Mock,
    ) -> None:
        request = httpx.Request("GET", "https://raw.githubusercontent.com/test")
        get.return_value = httpx.Response(404, request=request)

        version = get_current_version("owner/repo", "main", "ConfigPackage")

        self.assertEqual(version, "0.0.0")
        get.assert_called_once()


if __name__ == "__main__":
    unittest.main()
