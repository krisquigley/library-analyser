import unittest
from unittest.mock import patch

from music_exporer.frameworks.cli import main as cli


class MusicExporerCLITests(unittest.TestCase):
    def test_standalone_entrypoint_builds_server_from_configured_database(self):
        created = []
        class FakeServer:
            def serve_forever(self):
                created.append('served')
            def server_close(self):
                created.append('closed')
        settings = type('Settings', (), {'database': '/tmp/library.sqlite'})()
        with patch.object(cli, 'load_settings', return_value=settings), patch.object(cli, 'create_server', side_effect=lambda database, host, port: created.append((database, host, port)) or FakeServer()):
            self.assertEqual(cli.main(['--port', '0']), 0)
        self.assertEqual(created, [('/tmp/library.sqlite', '127.0.0.1', 0), 'served', 'closed'])

    def test_config_option_is_forwarded_to_settings_loader(self):
        class FakeServer:
            def serve_forever(self):
                pass
            def server_close(self):
                pass
        settings = type('Settings', (), {'database': '/tmp/library.sqlite'})()
        with patch.object(cli, 'load_settings', return_value=settings) as load_settings, patch.object(cli, 'create_server', return_value=FakeServer()):
            self.assertEqual(cli.main(['--config', '/tmp/music.toml', '--port', '0']), 0)
        load_settings.assert_called_once_with(config='/tmp/music.toml')

    def test_rejects_non_localhost_binding(self):
        with self.assertRaises(SystemExit):
            cli.main(['--host', '0.0.0.0'])


if __name__ == '__main__':
    unittest.main()
