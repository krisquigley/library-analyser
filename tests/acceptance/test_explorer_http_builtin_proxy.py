"""Built-in public fixture/server flow ignores environment proxy discovery."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import os
import threading
import unittest
from unittest.mock import patch

from tools.explorer_http_diagnostic import run_public_http_diagnostic


class BuiltinPublicHTTPProxyTests(unittest.TestCase):
    def test_builtin_flow_succeeds_without_contacting_environment_proxy(self):
        sentinel_hits = []

        class Sentinel(BaseHTTPRequestHandler):
            def do_GET(self):
                sentinel_hits.append(self.path)
                body = b'{}'
                self.send_response(502)
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        server = ThreadingHTTPServer(('127.0.0.1', 0), Sentinel)
        server.daemon_threads = True
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            proxy = 'http://127.0.0.1:' + str(server.server_port)
            with patch.dict(os.environ, {'http_proxy': proxy}, clear=True):
                self.assertNotIn('no_proxy', os.environ)
                self.assertNotIn('NO_PROXY', os.environ)
                # No injected factories: exercise the production composition.
                report = run_public_http_diagnostic(
                    track_count=12, seed=70, history_count=1,
                    sample_count=1, timeout_seconds=2)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

        self.assertEqual(sentinel_hits, [], 'environment proxy received built-in flow')
        self.assertEqual(len(report['requests']), 4)
        self.assertEqual(
            [(request['method'], request['route']) for request in report['requests']],
            [('GET', '/api/state'), ('GET', '/api/tracks/summary'),
             ('POST', '/api/current'), ('GET', '/api/tracks/:handle')])
        for request in report['requests']:
            self.assertEqual((request['status'], request['outcome']), (200, 'ok'))
            self.assertGreater(request['response_bytes'], 0)
        self.assertEqual(report['samples'][0]['outcome'], 'ok')
        required = {'summary_count', 'summary_page', 'selected_track',
                    'selected_locations', 'selected_latest_run'}
        self.assertTrue(required.issubset(
            {plan['operation'] for plan in report['sqlite']['plans']}))


if __name__ == '__main__':
    unittest.main()
