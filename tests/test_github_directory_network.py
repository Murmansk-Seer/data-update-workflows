import unittest
from unittest.mock import Mock, patch

import httpx

from scripts.config_sources._download_github_directory import (
    GitHubDownloadError,
    collect_directory_tasks,
)


class DirectoryNetworkTests(unittest.TestCase):
    @patch("scripts._common.time.sleep")
    def test_complete_response_retry_budget_and_permanent_missing(self, sleep):
        request = httpx.Request("GET", "https://api.github.com/test")
        client = Mock()
        client.get.side_effect = [
            httpx.Response(503, request=request),
            httpx.ReadError("interrupted body"),
            httpx.Response(200, request=request, json=[]),
        ]
        self.assertEqual(
            collect_directory_tasks(client, "o", "r", "p", None, "main"), []
        )
        self.assertEqual(client.get.call_count, 3)
        self.assertEqual(sleep.call_count, 2)
        client.reset_mock(side_effect=True)
        client.get.return_value = httpx.Response(404, request=request)
        with self.assertRaises(GitHubDownloadError):
            collect_directory_tasks(client, "o", "r", "p", None, "main")
        client.get.assert_called_once()
