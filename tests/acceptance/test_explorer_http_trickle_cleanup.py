"""Whole diagnostic lifecycle closes owned resources after finite trickles."""
from pathlib import Path
import threading
import time
import unittest

from music_explorer.frameworks.explorer.server import create_server
from tools.explorer_http_diagnostic import run_public_http_diagnostic


class PublicHTTPTrickleCleanupTests(unittest.TestCase):
    def test_success_and_error_body_deadlines_clean_fixture_server_and_handler(self):
        for status in (200, 503):
            with self.subTest(status=status):
                finished = threading.Event()
                stopped = threading.Event()
                closed = threading.Event()
                owned = []

                def factory(database_path, host='127.0.0.1', port=0):
                    database = Path(database_path)
                    server = create_server(str(database), host=host, port=port)
                    original_handler = server.RequestHandlerClass

                    class TrickleHandler(original_handler):
                        def do_GET(handler):
                            handler.send_response(status)
                            handler.send_header('Content-Length', '12')
                            handler.end_headers()
                            try:
                                for chunk in [b'{'] + [b' '] * 10 + [b'}']:
                                    handler.wfile.write(chunk)
                                    handler.wfile.flush()
                                    time.sleep(.020)
                            except OSError:
                                pass  # The client owns and closes its deadline socket.
                            finally:
                                handler.close_connection = True
                                finished.set()

                        def log_message(handler, *args):
                            pass

                    server.RequestHandlerClass = TrickleHandler
                    shutdown, close = server.shutdown, server.server_close

                    def stop_server():
                        shutdown()
                        stopped.set()

                    def close_server():
                        close()
                        closed.set()

                    server.shutdown, server.server_close = stop_server, close_server
                    owned.append((server, database))
                    return server

                report = run_public_http_diagnostic(
                    track_count=12, history_count=1, sample_count=1,
                    timeout_seconds=.050, server_factory=factory)
                self.assertEqual(len(report['requests']), 1)
                observation = report['requests'][0]
                self.assertEqual(observation['status'], status)
                self.assertEqual(observation['outcome'], 'timeout')
                self.assertGreater(observation['response_bytes'], 0)
                self.assertLess(observation['response_bytes'], 12)
                self.assertGreaterEqual(observation['elapsed_ms'], 35)
                self.assertLess(observation['elapsed_ms'], 150)
                self.assertEqual(report['profiles']['warm']['failures'], {'timeout': 1})
                self.assertEqual(report['profiles']['warm']['succeeded'], 0)
                self.assertIsNone(report['profiles']['warm']['p95_ms'])
                self.assertTrue(report['readonly']['unchanged'])
                self.assertTrue(finished.wait(2), 'finite HTTP handler leaked')
                self.assertTrue(stopped.is_set())
                self.assertTrue(closed.is_set())
                server, database = owned[0]
                self.assertEqual(server.socket.fileno(), -1)
                self.assertFalse(database.parent.exists(), 'owned fixture scratch leaked')


if __name__ == '__main__':
    unittest.main()
