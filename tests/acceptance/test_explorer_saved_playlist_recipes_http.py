"""Issue #139: the Explorer lists saved recipes and loads one for the playlist editor, read-only."""
import json
from pathlib import Path
import tempfile
import threading
import unittest
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import urlopen

from music_analyzer.infrastructure.persistence.playlist_recipes import SQLitePlaylistRecipeStore
from music_explorer.frameworks.explorer.server import create_server
from tests.acceptance.test_explorer_m3u_playlist_http_red import _create_playlist_http_db, _table_counts


class ExplorerSavedPlaylistRecipesHTTPTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        first_path, second_path = root / 'First.flac', root / 'Second.flac'
        for path in (first_path, second_path):
            path.write_bytes(b'existence only')
        self.db_path = root / 'analysis.sqlite'
        self.first, _second = _create_playlist_http_db(self.db_path, first_path, second_path)
        self.recipe = {'format': 'playlist-recipe', 'version': 2, 'start_track_id': self.first,
                       'bpm': {'min': 119, 'max': 125}, 'energy_plan': [{'shape': 'rise', 'tracks': 2}]}
        store = SQLitePlaylistRecipeStore(str(self.db_path))
        store.store_recipe('Warm-up', self.recipe, 1)
        store.store_recipe('Gone', {**self.recipe, 'start_track_id': 'sha256:gone'}, 1)
        server = create_server(str(self.db_path), host='127.0.0.1', port=0)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.shutdown)
        self.addCleanup(server.server_close)
        self.base = f'http://127.0.0.1:{server.server_port}'

    def _get(self, path):
        with urlopen(f'{self.base}{path}', timeout=5) as response:
            self.assertEqual('application/json', response.headers.get_content_type())
            return json.loads(response.read().decode('utf-8'))

    def _error(self, path):
        with self.assertRaises(HTTPError) as caught:
            urlopen(f'{self.base}{path}', timeout=5)
        self.assertEqual(400, caught.exception.code)
        return json.loads(caught.exception.read().decode('utf-8'))['error']

    def test_saved_recipes_are_listed_with_what_stops_one_loading(self):
        before = _table_counts(self.db_path)

        listed = self._get('/api/playlist-recipes')

        self.assertEqual(['Gone', 'Warm-up'], [recipe['name'] for recipe in listed['recipes']])
        self.assertEqual({'name', 'updated_at', 'problem'}, set(listed['recipes'][0]))
        self.assertIn('sha256:gone is not an available track', listed['recipes'][0]['problem'])
        self.assertIsNone(listed['recipes'][1]['problem'])
        self.assertEqual(before, _table_counts(self.db_path))

    def test_a_saved_recipe_loads_in_its_canonical_form(self):
        loaded = self._get('/api/playlist-recipes/load?' + urlencode({'name': 'Warm-up'}))

        self.assertEqual('Warm-up', loaded['name'])
        self.assertEqual({**self.recipe, 'bpm': {'min': 119.0, 'max': 125.0},
                          'energy_plan': [{'shape': 'rise', 'tracks': 2, 'energy_low': None, 'energy_high': None}],
                          'harmonic_mixing': {'enabled': True, 'minimum_key_strength': 0.5}, 'mood_hold': None},
                         loaded['recipe'])
        self.assertNotIn('.flac', json.dumps(loaded))

    def test_a_recipe_that_cannot_be_loaded_is_a_400_saying_why(self):
        for query, message in (({'name': 'Gone'}, 'The saved recipe "Gone" cannot be loaded: Its start track sha256:gone'),
                               ({'name': 'Nope'}, 'No saved recipe named "Nope"'),
                               ({}, 'A recipe name is 1 to 100 printable characters'),
                               ({'name': ' '}, 'A recipe name is 1 to 100 printable characters')):
            with self.subTest(query=query):
                self.assertIn(message, self._error('/api/playlist-recipes/load?' + urlencode(query)))


if __name__ == '__main__':
    unittest.main()
