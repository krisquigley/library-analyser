"""Issue #258: the Explorer streams a track's available audio file, read-only, in the byte ranges a seek bar asks for."""
import json
from pathlib import Path
import tempfile
import threading
import unittest
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from music_explorer.frameworks.explorer.server import create_server
from tests.acceptance.test_explorer_m3u_playlist_http_red import _create_playlist_http_db, _table_counts
from tests.support.synthetic_flac import FRAMES, PICTURE, STREAMINFO, metadata_block, picture_body, synthetic_flac

SYNTHETIC_AUDIO = bytes(range(256)) * 300


class ExplorerTrackAudioHTTPTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        self.first_path, second_path = root / 'First.flac', root / 'Second.flac'
        self.first_path.write_bytes(SYNTHETIC_AUDIO)
        second_path.write_bytes(b'second')
        self.db_path = root / 'analysis.sqlite'
        self.first, self.second = _create_playlist_http_db(self.db_path, self.first_path, second_path)
        server = create_server(str(self.db_path), host='127.0.0.1', port=0)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.shutdown)
        self.addCleanup(server.server_close)
        self.base = f'http://127.0.0.1:{server.server_port}'

    def _get(self, query, headers=None):
        return urlopen(Request(f'{self.base}/api/track-audio?{query}', headers=headers or {}), timeout=5)

    def _refused(self, query, headers=None):
        with self.assertRaises(HTTPError) as refused:
            self._get(query, headers)
        self.addCleanup(refused.exception.close)
        return refused.exception

    def test_the_whole_file_is_served_as_it_is_without_naming_it(self):
        before = _table_counts(self.db_path), self.first_path.read_bytes()
        with self._get(urlencode({'track': self.first})) as response:
            body = response.read()
            self.assertEqual((200, 'audio/flac', 'bytes', str(len(SYNTHETIC_AUDIO))),
                             (response.status, response.headers['Content-Type'], response.headers['Accept-Ranges'],
                              response.headers['Content-Length']))
            self.assertNotIn('First', ' '.join(f'{name}: {value}' for name, value in response.headers.items()))
        self.assertEqual(SYNTHETIC_AUDIO, body)
        self.assertEqual(before, (_table_counts(self.db_path), self.first_path.read_bytes()), 'nothing is written')

    def test_a_seek_gets_the_byte_range_it_asks_for(self):
        with self._get(urlencode({'track': self.first}), {'Range': 'bytes=1000-1099'}) as response:
            self.assertEqual((206, f'bytes 1000-1099/{len(SYNTHETIC_AUDIO)}', '100'),
                             (response.status, response.headers['Content-Range'], response.headers['Content-Length']))
            self.assertEqual(SYNTHETIC_AUDIO[1000:1100], response.read())

    def test_a_range_past_the_end_is_416_with_the_file_size(self):
        refused = self._refused(urlencode({'track': self.first}), {'Range': f'bytes={len(SYNTHETIC_AUDIO)}-'})
        self.assertEqual((416, f'bytes */{len(SYNTHETIC_AUDIO)}'), (refused.code, refused.headers['Content-Range']))

    def test_a_track_that_cannot_be_heard_is_a_json_error_the_listener_can_read(self):
        for query, code, message in ((urlencode({'track': 'sha256:' + 'f' * 64}), 404, 'This track has no available audio file'),
                                     ('', 400, 'Name one track to listen to'),
                                     (urlencode([('track', self.first), ('track', self.second)]), 400, 'Name one track to listen to')):
            with self.subTest(query=query):
                refused = self._refused(query)
                self.assertEqual((code, {'error': message}), (refused.code, json.loads(refused.read())))

    def test_a_file_gone_from_the_disk_is_a_404_that_does_not_name_it(self):
        self.first_path.unlink()
        refused = self._refused(urlencode({'track': self.first}))
        body = refused.read().decode('utf-8')
        self.assertEqual((404, {'error': "This track's audio file is missing"}), (refused.code, json.loads(body)))
        self.assertNotIn('First', body)

    def test_a_flac_whose_cover_picture_has_no_type_plays_without_it(self):
        # #269: Chromium refuses a FLAC whose picture block names no MIME type; the picture is left out of the stream.
        content = synthetic_flac((STREAMINFO, bytes(34)), (PICTURE, picture_body(b'', bytes(3000))))
        self.first_path.write_bytes(content)
        served = b'fLaC' + metadata_block(STREAMINFO, bytes(34), last=True) + FRAMES
        with self._get(urlencode({'track': self.first})) as response:
            self.assertEqual((200, str(len(served)), served), (response.status, response.headers['Content-Length'], response.read()))
        with self._get(urlencode({'track': self.first}), {'Range': 'bytes=30-49'}) as response:
            self.assertEqual((206, f'bytes 30-49/{len(served)}', served[30:50]),
                             (response.status, response.headers['Content-Range'], response.read()))
        self.assertEqual(content, self.first_path.read_bytes(), 'the file is never changed')


if __name__ == '__main__':
    unittest.main()
