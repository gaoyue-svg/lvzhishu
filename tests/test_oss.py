"""OSS 对象操作的网络故障恢复测试。"""

from __future__ import annotations

import io
import ssl
import unittest
from unittest.mock import mock_open, patch
from urllib.error import HTTPError, URLError

from backend.storage.oss import OSSClient


class OSSDownloadRetryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = OSSClient("https://oss-cn-hangzhou.aliyuncs.com", "ak", "secret")

    def test_transient_ssl_error_is_retried(self):
        transient = URLError(ssl.SSLEOFError(8, "unexpected eof"))
        target_open = mock_open()
        with (
            patch("backend.storage.oss.urlopen", side_effect=[transient, io.BytesIO(b"docx-data")]) as mocked,
            patch("backend.storage.oss.Path.open", target_open),
            patch("backend.storage.oss.Path.unlink"),
            patch("backend.storage.oss.sleep") as sleep_mock,
            patch("backend.storage.oss.settings.oss_download_retry", 3),
        ):
            self.client._download_file_sync("bucket", "key", "contract.docx")

        target_open().write.assert_called_once_with(b"docx-data")
        self.assertEqual(mocked.call_count, 2)
        sleep_mock.assert_called_once()

    def test_permanent_http_403_is_not_retried(self):
        forbidden = HTTPError("https://example.test", 403, "Forbidden", {}, None)
        with (
            patch("backend.storage.oss.urlopen", side_effect=forbidden) as mocked,
            patch("backend.storage.oss.Path.unlink"),
            patch("backend.storage.oss.sleep") as sleep_mock,
            patch("backend.storage.oss.settings.oss_download_retry", 3),
        ):
            with self.assertRaises(HTTPError):
                self.client._download_file_sync("bucket", "key", "contract.docx")

        self.assertEqual(mocked.call_count, 1)
        sleep_mock.assert_not_called()


if __name__ == "__main__":
    unittest.main()
