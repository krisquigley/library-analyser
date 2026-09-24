import unittest
from unittest.mock import patch

import music_analyzer.frameworks.explorer.server as legacy_server
from music_explorer.frameworks.explorer.server import create_server


class MusicExplorerServerOwnershipTests(unittest.TestCase):
    def test_legacy_server_delegates_to_standalone_package(self):
        with patch.object(legacy_server._standalone, 'create_server', return_value='server') as delegated:
            self.assertEqual(legacy_server.create_server('/tmp/library.db', host='127.0.0.1', port=0), 'server')
        delegated.assert_called_once_with('/tmp/library.db', '127.0.0.1', 0)

    def test_standalone_server_is_importable_entrypoint(self):
        self.assertEqual(create_server.__module__, 'music_explorer.frameworks.explorer.server')


if __name__ == '__main__':
    unittest.main()
