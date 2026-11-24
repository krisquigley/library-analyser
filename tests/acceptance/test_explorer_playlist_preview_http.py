"""Issue #138: the playlist preview endpoint lists the same tracks as the M3U download of the same recipe."""
import json
from pathlib import Path
import tempfile
import threading
import unittest
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import urlopen

from music_explorer.frameworks.explorer.server import create_server
from tests.acceptance.test_explorer_m3u_playlist_http_red import _create_playlist_http_db, _table_counts


class ExplorerPlaylistPreviewHTTPTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        first_path, second_path = root / 'First.flac', root / 'Second.flac'
        for path in (first_path, second_path):
            path.write_bytes(b'existence only; server must not read audio bytes')
        self.db_path = root / 'analysis.sqlite'
        self.first, self.second = _create_playlist_http_db(self.db_path, first_path, second_path)
        server = create_server(str(self.db_path), host='127.0.0.1', port=0)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.shutdown)
        self.addCleanup(server.server_close)
        self.base = f'http://127.0.0.1:{server.server_port}'

    def _query(self, *pairs):
        return urlencode([('start_track_id', self.first), ('bpm_min', '119'), ('bpm_max', '125'), *pairs])

    def _preview(self, query):
        with urlopen(f'{self.base}/api/playlists/preview?{query}', timeout=5) as response:
            self.assertEqual('application/json', response.headers.get_content_type())
            return json.loads(response.read().decode('utf-8'))

    def _m3u_track_count(self, query):
        with urlopen(f'{self.base}/api/playlists/m3u?{query}', timeout=5) as response:
            return len([line for line in response.read().decode('utf-8').splitlines() if not line.startswith('#')])

    def test_the_preview_lists_the_tracks_the_m3u_download_would(self):
        for pairs in ([('length', '2')], [('length', '2'), ('arc', 'rise')],
                      [('arc', 'rise'), ('arc', 'fall'), ('arc_tracks', '1'), ('arc_tracks', '1')]):
            with self.subTest(pairs=pairs):
                preview = self._preview(self._query(*pairs))
                self.assertEqual([self.first, self.second], [track['track_id'] for track in preview['tracks']])
                self.assertEqual(self._m3u_track_count(self._query(*pairs)), len(preview['tracks']))
                self.assertEqual((True, None), (preview['complete'], preview['warning']))

    def test_the_preview_shows_each_track_and_transition_without_file_paths(self):
        before = _table_counts(self.db_path)
        preview = self._preview(self._query(('length', '2')))

        self.assertEqual({'track_id', 'title', 'artist', 'bpm', 'key', 'camelot', 'arousal', 'energy_level', 'energy_target',
                          'duration_seconds'},
                         set(preview['tracks'][0]))
        self.assertEqual([(self.first, self.second)],
                         [(step['from_track_id'], step['to_track_id']) for step in preview['transitions']])
        self.assertNotIn('.flac', json.dumps(preview))
        self.assertEqual(before, _table_counts(self.db_path), 'the preview never writes the analysis database')

    def test_an_invalid_recipe_is_a_json_400_with_the_same_message_as_the_download(self):
        for query in (self._query(('length', '0')), self._query(('arc', 'wave'), ('length', '2')),
                      self._query(('arc', 'rise'), ('arc', 'fall'), ('arc_tracks', '1'))):
            with self.subTest(query=query):
                with self.assertRaises(HTTPError) as preview:
                    urlopen(f'{self.base}/api/playlists/preview?{query}', timeout=5)
                with self.assertRaises(HTTPError) as download:
                    urlopen(f'{self.base}/api/playlists/m3u?{query}', timeout=5)
                self.assertEqual(400, preview.exception.code)
                self.assertEqual(json.loads(download.exception.read())['error'], json.loads(preview.exception.read())['error'])


if __name__ == '__main__':
    unittest.main()
