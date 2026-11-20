"""Issue #146: the Explorer serves its browser app's ES modules, and nothing else under /app/."""
import tempfile
import threading
import unittest
from importlib import resources
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import urlopen

from music_explorer.frameworks.explorer.server import create_server
from tests.acceptance.test_explorer_m3u_playlist_http_red import _create_playlist_http_db


class ExplorerAppModuleServingTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        for name in ('First.flac', 'Second.flac'):
            (root / name).write_bytes(b'existence only')
        _create_playlist_http_db(root / 'analysis.sqlite', root / 'First.flac', root / 'Second.flac')
        self.server = create_server(str(root / 'analysis.sqlite'), host='127.0.0.1', port=0)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.base = f'http://127.0.0.1:{self.server.server_port}'

    def test_a_module_is_served_as_javascript(self):
        expected = resources.files('music_explorer.frameworks.explorer.assets').joinpath(
            'app/domain/playlist-recipe.js').read_text(encoding='utf-8')

        with urlopen(self.base + '/app/domain/playlist-recipe.js', timeout=5) as response:
            self.assertEqual('text/javascript', response.headers.get_content_type())
            self.assertEqual(expected, response.read().decode('utf-8'))

    def test_the_index_loads_the_app_from_its_composition_root(self):
        with urlopen(self.base + '/', timeout=5) as response:
            self.assertIn('<script type="module" src="/app/main/main.js"></script>', response.read().decode('utf-8'))
        with urlopen(self.base + '/app/main/main.js', timeout=5) as response:
            self.assertEqual('text/javascript', response.headers.get_content_type())

    def test_the_old_single_script_is_gone(self):
        with self.assertRaises(HTTPError) as raised:
            urlopen(self.base + '/app.js', timeout=5)
        self.assertEqual(404, raised.exception.code)

    def test_anything_else_under_app_is_not_found(self):
        for path in ('/app/domain/missing.js', '/app/package.json', '/app/domain/Playlist-Recipe.JS',
                     '/app/../server.py', '/app/domain/../../app.js', '/app/%2e%2e/app.js', '/app/domain/',
                     '/app/application/.gitkeep'):
            with self.subTest(path=path):
                with self.assertRaises(HTTPError) as raised:
                    urlopen(self.base + path, timeout=5)
                self.assertEqual(404, raised.exception.code)


if __name__ == '__main__':
    unittest.main()
