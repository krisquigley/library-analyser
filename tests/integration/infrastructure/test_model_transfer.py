import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from music_analyzer.application.dto.models import ModelError
from music_analyzer.infrastructure.models.transfer import HTTPSTransfer, OfficialRedirectHandler


class Response(io.BytesIO):
    def __init__(self, content, url='https://essentia.upf.edu/models/test.pb'):
        super().__init__(content)
        self.url = url
        self.headers = {'Content-Length': str(len(content))}
        self.status = 200

    def geturl(self):
        return self.url


class TransferTests(unittest.TestCase):
    def test_streamed_download_and_limits(self):
        for content, size, success in [(b'abc', 3, True), (b'a', 3, False), (b'abcd', 3, False)]:
            with self.subTest(content=content), tempfile.TemporaryDirectory() as root:
                path = str(Path(root) / 'asset')
                with patch('music_analyzer.infrastructure.models.transfer.build_opener') as opener:
                    opener.return_value.open.return_value = Response(content)
                    if success:
                        HTTPSTransfer().download('https://essentia.upf.edu/models/test.pb', path, size)
                        self.assertEqual(Path(path).read_bytes(), b'abc')
                    else:
                        with self.assertRaises(ModelError):
                            HTTPSTransfer().download('https://essentia.upf.edu/models/test.pb', path, size)

    def test_rejects_insecure_or_external_redirect_before_request(self):
        handler = OfficialRedirectHandler()
        for url in ('http://essentia.upf.edu/models/a', 'https://evil.example/a'):
            with self.subTest(url=url), self.assertRaises(ModelError):
                handler.redirect_request(None, None, 302, '', {}, url)

    def test_transfer_failure_is_actionable(self):
        with tempfile.TemporaryDirectory() as root, patch('music_analyzer.infrastructure.models.transfer.build_opener') as opener:
            opener.return_value.open.side_effect = TimeoutError('timed out')
            with self.assertRaisesRegex(ModelError, 'retry'):
                HTTPSTransfer().download('https://essentia.upf.edu/models/test.pb', str(Path(root) / 'asset'), 3)
