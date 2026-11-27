"""#277: POST /api/playlists/hand-built downloads the listener's own list of tracks as an M3U, in their order.
#287: POST /api/playlists/hand-built/preview previews it as the recipe preview does."""
import json
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from music_explorer.domain.hand_built_playlist import MAXIMUM_HAND_BUILT_TRACKS
from music_explorer.frameworks.explorer.server import MAX_BODY, create_server
from tests.acceptance.test_explorer_m3u_playlist_http_red import _create_playlist_http_db, _table_counts


class HandBuiltPlaylistHTTPTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        self.db_path = root / 'analysis.sqlite'
        self.first_path, self.second_path = root / 'First.flac', root / 'Second.flac'
        for path in (self.first_path, self.second_path):
            path.write_bytes(b'existence only; the server must not read audio bytes')
        self.first, self.second = _create_playlist_http_db(self.db_path, self.first_path, self.second_path)
        self.server = create_server(str(self.db_path), host='127.0.0.1', port=0)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.base = f'http://127.0.0.1:{self.server.server_port}'

    def download(self, body, origin='SELF'):
        return self.post('/api/playlists/hand-built', body, origin)

    def preview(self, body, origin='SELF'):
        return self.post('/api/playlists/hand-built/preview', body, origin)

    def post(self, path, body, origin):
        headers = {'Content-Type': 'application/json'}
        if origin is not None:
            headers['Origin'] = self.base if origin == 'SELF' else origin
        request = Request(f'{self.base}{path}', data=json.dumps(body).encode('utf-8'), headers=headers, method='POST')
        try:
            with urlopen(request, timeout=5) as response:
                return response.status, response.headers, response.read().decode('utf-8')
        except HTTPError as error:
            return error.code, error.headers, error.read().decode('utf-8')

    def test_the_tracks_download_in_the_listeners_order_and_nothing_is_written(self):
        before = (_table_counts(self.db_path), self.db_path.read_bytes())
        status, headers, body = self.download({'track_ids': [self.second, self.first]})
        self.assertEqual(status, 200)
        self.assertEqual(headers['Content-Type'], 'audio/x-mpegurl; charset=utf-8')
        self.assertEqual(headers['Content-Disposition'], 'attachment; filename="hand-built-playlist.m3u"')
        self.assertEqual(body, f'#EXTM3U\n{self.second_path}\n{self.first_path}\n')
        self.assertEqual((_table_counts(self.db_path), self.db_path.read_bytes()), before)

    def test_the_longest_playlist_of_full_track_ids_fits_in_one_request(self):
        longest = {'track_ids': [f'sha256:{number:064x}' for number in range(MAXIMUM_HAND_BUILT_TRACKS)]}
        self.assertLess(len(json.dumps(longest).encode('utf-8')), MAX_BODY)

    def test_only_the_explorers_own_page_may_ask(self):
        for origin in (None, 'http://example.invalid'):
            with self.subTest(origin=origin):
                status, _, body = self.download({'track_ids': [self.first]}, origin=origin)
                self.assertEqual((status, json.loads(body)), (403, {'error': 'Only the Explorer page can download this playlist'}))

    def test_a_request_outside_the_schema_is_refused_with_its_reason(self):
        for request, message in (([self.first], 'Send the playlist as {"track_ids": [...]}'),
                                 ({'track_ids': self.first}, 'Send the playlist as {"track_ids": [...]}'),
                                 ({'track_ids': [self.first], 'extra': 1}, 'Send the playlist as {"track_ids": [...]}'),
                                 ({'track_ids': []}, 'Add at least one track to the playlist'),
                                 ({'track_ids': [self.first, self.first]}, 'The playlist names a track more than once'),
                                 ({'track_ids': [self.first, 'sha256:' + '9' * 64]},
                                  'Track 2 of the playlist is no longer playable from the library; remove it and try again')):
            with self.subTest(request=request):
                status, _, body = self.download(request)
                self.assertEqual((status, json.loads(body)), (400, {'error': message}))

    def test_287_the_preview_lists_the_tracks_in_the_listeners_order_and_nothing_is_written(self):
        before = (_table_counts(self.db_path), self.db_path.read_bytes())
        status, headers, body = self.preview({'track_ids': [self.second, self.first]})
        preview = json.loads(body)
        self.assertEqual((status, headers['Content-Type']), (200, 'application/json; charset=utf-8'))
        self.assertEqual([track['track_id'] for track in preview['tracks']], [self.second, self.first])
        self.assertEqual([(step['from_track_id'], step['to_track_id']) for step in preview['transitions']],
                         [(self.second, self.first)])
        self.assertEqual((preview['complete'], preview['warning']), (True, None))
        self.assertTrue(all(track['energy_target'] is None for track in preview['tracks']), 'a hand-built list has no arc')
        self.assertTrue(all('valence' in track for track in preview['tracks']), '#294: each track says its valence')
        self.assertEqual((_table_counts(self.db_path), self.db_path.read_bytes()), before)

    def test_287_a_track_no_longer_playable_is_left_out_of_the_preview_and_said_so(self):
        status, _, body = self.preview({'track_ids': [self.first, 'sha256:' + '9' * 64]})
        preview = json.loads(body)
        self.assertEqual((status, [track['track_id'] for track in preview['tracks']], preview['complete']),
                         (200, [self.first], False))
        self.assertEqual(preview['warning'], '1 of its tracks is no longer playable from the library; remove it to download it')

    def test_287_only_the_explorers_own_page_may_preview_and_the_schema_holds(self):
        for origin in (None, 'http://example.invalid'):
            with self.subTest(origin=origin):
                status, _, body = self.preview({'track_ids': [self.first]}, origin=origin)
                self.assertEqual((status, json.loads(body)), (403, {'error': 'Only the Explorer page can preview this playlist'}))
        for request, message in (({'track_ids': self.first}, 'Send the playlist as {"track_ids": [...]}'),
                                 ({'track_ids': [self.first, self.first]}, 'The playlist names a track more than once')):
            with self.subTest(request=request):
                status, _, body = self.preview(request)
                self.assertEqual((status, json.loads(body)), (400, {'error': message}))


if __name__ == '__main__':
    unittest.main()
