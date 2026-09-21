import io
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from music_analyzer.frameworks.cli import main as cli


class ExplorerCliTests(unittest.TestCase):
    def test_explorer_command_binds_localhost_and_uses_configured_database(self):
        class FakeServer:
            server_port = 8765
            def serve_forever(self):
                raise KeyboardInterrupt()

        created = []
        with patch.object(cli, 'load_settings', return_value=type('Settings', (), {'database': '/tmp/analysis.sqlite'})()):
            with patch.object(cli, 'create_server', side_effect=lambda database, host, port: created.append((database, host, port)) or FakeServer()):
                with redirect_stdout(io.StringIO()):
                    self.assertEqual(cli.main(['explorer']), 130)
        self.assertEqual(created, [('/tmp/analysis.sqlite', '127.0.0.1', 8765)])

    def test_explorer_rejects_non_localhost_bind(self):
        with self.assertRaises(SystemExit):
            cli.main(['explorer', '--host', '0.0.0.0'])


if __name__ == '__main__':
    unittest.main()
