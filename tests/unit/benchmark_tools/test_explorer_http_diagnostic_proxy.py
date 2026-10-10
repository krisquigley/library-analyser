"""Built-in diagnostic transport must never discover environment proxies."""
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import os
import threading
import unittest
from unittest.mock import patch

from tools.explorer_http_diagnostic import _request


@contextmanager
def _json_server(status, hits):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            hits.append(self.path)
            body = b'{"source": "loopback"}'
            self.send_response(status)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield 'http://127.0.0.1:' + str(server.server_port)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


class PublicHTTPDiagnosticProxyTests(unittest.TestCase):
    def test_localhost_requests_ignore_http_proxy_without_no_proxy(self):
        for status in (200, 503):
            with self.subTest(status=status):
                sentinel_hits, origin_hits = [], []
                with _json_server(200, sentinel_hits) as proxy:
                    with _json_server(status, origin_hits) as origin:
                        # clear=True removes both no_proxy spellings and all
                        # inherited proxies; the sentinel is loopback only.
                        with patch.dict(os.environ, {'http_proxy': proxy}, clear=True):
                            self.assertNotIn('no_proxy', os.environ)
                            self.assertNotIn('NO_PROXY', os.environ)
                            observations, intervals = [], []
                            payload, outcome = _request(
                                origin, '/api/state', 'GET', 1,
                                observations, intervals, 'get_state')
                self.assertEqual(sentinel_hits, [], 'environment proxy received request')
                self.assertEqual(origin_hits, ['/api/state'])
                self.assertEqual(observations[0]['status'], status)
                self.assertEqual(observations[0]['response_bytes'], 22)
                self.assertEqual(outcome, 'ok' if status == 200 else 'http_error')
                self.assertEqual(payload, {'source': 'loopback'} if status == 200 else None)


if __name__ == '__main__':
    unittest.main()
