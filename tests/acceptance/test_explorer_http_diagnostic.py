"""PR4c red contracts: tiny generated data, real loopback HTTP, no private target.

The missing opt-in harness is checked inside each test, so baseline collection
still succeeds. These tests intentionally do not implement the harness or claim
browser/render/latency-budget evidence.
"""
import importlib
import importlib.util
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import math
import threading
import unittest
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from music_explorer.frameworks.explorer.server import create_server


class PublicHTTPDiagnosticTests(unittest.TestCase):
    def tool(self):
        name = 'tools.explorer_http_diagnostic'
        self.assertIsNotNone(
            importlib.util.find_spec(name),
            'PR4c missing bounded public HTTP diagnostic tool: ' + name,
        )
        tool = importlib.import_module(name)
        self.assertTrue(callable(getattr(tool, 'run_public_http_diagnostic', None)),
                        'PR4c missing run_public_http_diagnostic entrypoint')
        return tool

    def factory(self, *, reject_current=False, stall_state=False,
                body_status=None, stall_body=False, detail_override=False,
                detail_payload=None, redirect=None):
        """Observe public server I/O; alter only HTTP responses for failure cases."""
        calls = []
        servers = []
        release = threading.Event()
        stalled_handler_finished = threading.Event()
        self.addCleanup(release.set)

        def make_server(database_path, host='127.0.0.1', port=0):
            self.assertEqual(host, '127.0.0.1')
            self.assertEqual(port, 0, 'diagnostic must not bind a fixed/user port')
            database = Path(database_path)
            self.assertTrue(database.is_file())
            server = create_server(str(database), host=host, port=port)
            original_handler = server.RequestHandlerClass

            class ObservedHandler(original_handler):
                def do_GET(handler):
                    calls.append(('GET', handler.path))
                    if urlsplit(handler.path).path == '/api/state' and redirect:
                        handler.send_response(302)
                        handler.send_header('Location', redirect)
                        handler.send_header('Content-Length', '0')
                        handler.end_headers()
                        return
                    if urlsplit(handler.path).path == '/api/state' and body_status:
                        handler.send_response(body_status)
                        handler.send_header('Content-Length', '100')
                        handler.end_headers()
                        handler.wfile.write(b'{}')
                        handler.wfile.flush()
                        if stall_body:
                            try:
                                release.wait(5)
                            finally:
                                stalled_handler_finished.set()
                        handler.close_connection = True
                        return
                    if (detail_override and handler.path.startswith('/api/tracks/')
                            and not handler.path.startswith('/api/tracks/summary')):
                        handler._json(detail_payload)
                        return
                    if stall_state and urlsplit(handler.path).path == '/api/state':
                        # The client timeout must release the harness. The test
                        # event bounds handler lifetime without sleeping/timing CI.
                        try:
                            release.wait(5)
                        finally:
                            stalled_handler_finished.set()
                        return
                    super().do_GET()

                def do_POST(handler):
                    calls.append(('POST', handler.path))
                    if reject_current:
                        handler._json({'error': 'SECRET_HTTP_BODY /private/music.flac'}, 400)
                        return
                    super().do_POST()

                def log_message(handler, *args):
                    pass

            server.RequestHandlerClass = ObservedHandler
            stopped = threading.Event()
            closed = threading.Event()
            original_shutdown, original_close = server.shutdown, server.server_close

            def shutdown():
                original_shutdown()
                stopped.set()

            def close():
                release.set()
                original_close()
                if stall_state or stall_body:
                    self.assertTrue(stalled_handler_finished.wait(2),
                                    'timed-out HTTP handler leaked')
                closed.set()

            server.shutdown, server.server_close = shutdown, close
            servers.append((server, database, stopped, closed))
            return server

        return make_server, calls, servers

    def assert_cleaned(self, servers):
        self.assertEqual(len(servers), 1)
        server, database, stopped, closed = servers[0]
        self.assertTrue(stopped.is_set(), 'server.shutdown not completed')
        self.assertTrue(closed.is_set(), 'server.server_close not completed')
        self.assertEqual(server.socket.fileno(), -1)
        self.assertFalse(database.parent.exists(), 'owned fixture scratch leaked')

    def run_tiny(self, tool, factory, timeout_seconds=2):
        return tool.run_public_http_diagnostic(
            track_count=12, seed=70, history_count=1, allow_large=False,
            sample_count=1, timeout_seconds=timeout_seconds,
            server_factory=factory,
        )

    def test_tiny_public_http_inventory_is_bounded_and_scratch_is_owned(self):
        tool = self.tool()
        factory, calls, servers = self.factory()
        report = self.run_tiny(tool, factory)

        normalized = [(method, '/api/tracks/:handle' if path.startswith('/api/tracks/')
                       and not path.startswith('/api/tracks/summary') else urlsplit(path).path)
                      for method, path in calls]
        self.assertEqual(normalized, [
            ('GET', '/api/state'), ('GET', '/api/tracks/summary'),
            ('POST', '/api/current'), ('GET', '/api/tracks/:handle'),
        ])
        query = parse_qs(urlsplit(calls[1][1]).query)
        self.assertGreaterEqual(int(query['limit'][0]), 1)
        self.assertLessEqual(int(query['limit'][0]), 100)
        self.assertTrue(query.get('query', query.get('q', ['']))[0].strip(),
                        'diagnose bounded nonblank search, not unfiltered listing')
        self.assertEqual(report['request_inventory']['requests'], [
            {'method': 'GET', 'route': '/api/state', 'count': 1},
            {'method': 'GET', 'route': '/api/tracks/:handle', 'count': 1},
            {'method': 'GET', 'route': '/api/tracks/summary', 'count': 1},
            {'method': 'POST', 'route': '/api/current', 'count': 1},
        ])
        self.assertEqual(len(report['requests']), 4)
        for request in report['requests']:
            self.assertEqual(request['status'], 200)
            self.assertEqual(request['outcome'], 'ok')
            self.assertTrue(math.isfinite(request['elapsed_ms']))
            self.assertGreaterEqual(request['elapsed_ms'], 0)
            self.assertGreater(request['response_bytes'], 0)
        self.assertEqual(report['scope'], 'public-synthetic-http-only')
        self.assertEqual(report['browser_evidence'], 'not_measured')
        self.assertEqual(report['latency_budget_result'], 'not_asserted')
        self.assert_cleaned(servers)

    def test_rejected_selection_retains_http_status_and_skips_detail(self):
        tool = self.tool()
        factory, calls, servers = self.factory(reject_current=True)
        report = self.run_tiny(tool, factory)

        self.assertEqual([method for method, _ in calls], ['GET', 'GET', 'POST'])
        rejected = report['requests'][-1]
        self.assertEqual((rejected['method'], rejected['route']), ('POST', '/api/current'))
        self.assertEqual(rejected['status'], 400)
        self.assertEqual(rejected['outcome'], 'http_error')
        self.assertEqual(report['samples'][0]['outcome'], 'http_error')
        published = json.dumps(report, allow_nan=False)
        self.assertNotIn('SECRET_HTTP_BODY', published)
        self.assertNotIn('/private/music.flac', published)
        self.assert_cleaned(servers)

    def test_timeout_is_retained_without_fabricated_status_and_cleans_server(self):
        tool = self.tool()
        factory, calls, servers = self.factory(stall_state=True)
        report = self.run_tiny(tool, factory, timeout_seconds=0.05)

        self.assertEqual(calls, [('GET', '/api/state')])
        self.assertEqual(len(report['requests']), 1)
        timed_out = report['requests'][0]
        self.assertIsNone(timed_out['status'])
        self.assertEqual(timed_out['outcome'], 'timeout')
        self.assertEqual(report['samples'][0]['outcome'], 'timeout')
        self.assert_cleaned(servers)

    def test_body_failures_retain_status_partial_bytes_elapsed_and_cleanup(self):
        for status in (200, 400):
            for stalled in (False, True):
                with self.subTest(status=status, stalled=stalled):
                    factory, calls, servers = self.factory(
                        body_status=status, stall_body=stalled)
                    report = self.run_tiny(self.tool(), factory, timeout_seconds=0.05)
                    self.assertEqual(calls, [('GET', '/api/state')])
                    observed = report['requests'][0]
                    outcome = 'timeout' if stalled else 'connection_error'
                    self.assertEqual(observed['status'], status)
                    self.assertEqual(observed['response_bytes'], 2)
                    self.assertEqual(observed['outcome'], outcome)
                    self.assertEqual(report['samples'][0]['outcome'], outcome)
                    self.assertTrue(math.isfinite(observed['elapsed_ms']))
                    self.assertGreater(observed['elapsed_ms'], 0)
                    self.assertNotIn('IncompleteRead', json.dumps(report))
                    self.assert_cleaned(servers)

    def test_detail_requires_object_with_selected_handle(self):
        for detail in (None, {'handle': 'wrong-handle'}):
            with self.subTest(detail=detail):
                factory, calls, servers = self.factory(
                    detail_override=True, detail_payload=detail)
                report = self.run_tiny(self.tool(), factory)
                self.assertEqual(len(calls), 4)
                self.assertEqual(report['samples'][0]['outcome'], 'invalid_response')
                self.assertEqual(report['requests'][-1]['outcome'], 'invalid_response')
                self.assert_cleaned(servers)

    def test_redirect_is_failed_without_following_or_external_inventory(self):
        hits = []

        class SentinelHandler(BaseHTTPRequestHandler):
            def do_GET(handler):
                hits.append(handler.path)
                handler.send_response(200)
                handler.end_headers()
                handler.wfile.write(b'{"selection_epoch": 0}')

            def log_message(handler, *args):
                pass

        # A second loopback port is a distinct origin, without contacting any
        # external network even if redirect prevention regresses.
        sentinel = ThreadingHTTPServer(('127.0.0.1', 0), SentinelHandler)
        thread = threading.Thread(target=sentinel.serve_forever, daemon=True)
        thread.start()

        def close_sentinel():
            sentinel.shutdown()
            sentinel.server_close()
            thread.join()

        self.addCleanup(close_sentinel)
        external_origin = f'http://127.0.0.1:{sentinel.server_port}/SECRET_PATH'
        for location in ('/api/state-redirected', external_origin):
            with self.subTest(location=location):
                factory, calls, servers = self.factory(redirect=location)
                report = self.run_tiny(self.tool(), factory)
                self.assertEqual(calls, [('GET', '/api/state')])
                self.assertEqual(len(report['requests']), 1)
                self.assertEqual(report['requests'][0]['status'], 302)
                self.assertEqual(report['requests'][0]['outcome'], 'http_error')
                self.assertEqual(report['samples'][0]['outcome'], 'http_error')
                self.assertEqual(report['request_inventory']['requests'], [
                    {'method': 'GET', 'route': '/api/state', 'count': 1}])
                self.assertEqual(hits, [], 'redirect contacted another origin')
                self.assertNotIn(external_origin, json.dumps(report))
                self.assertNotIn('SECRET_PATH', json.dumps(report))
                self.assert_cleaned(servers)

    def test_server_startup_failure_propagates_and_cleans_owned_scratch(self):
        tool = self.tool()
        databases = []

        def failed_server(database_path, host='127.0.0.1', port=0):
            database = Path(database_path)
            self.assertTrue(database.is_file())
            databases.append(database)
            raise OSError('synthetic server startup failure')

        with self.assertRaises(OSError):
            self.run_tiny(tool, failed_server)
        self.assertEqual(len(databases), 1)
        self.assertFalse(databases[0].parent.exists(),
                         'server startup failure leaked owned fixture scratch')

    def test_invalid_or_expensive_profiles_fail_before_starting_server(self):
        tool = self.tool()
        started = []

        def forbidden_server(*args, **kwargs):
            started.append(True)
            self.fail('invalid profile started HTTP server')

        for options in ({'sample_count': 0}, {'sample_count': True},
                        {'sample_count': 1.5}, {'sample_count': 101},
                        {'timeout_seconds': 0}, {'timeout_seconds': 61},
                        {'timeout_seconds': float('nan')},
                        {'timeout_seconds': float('inf')},
                        {'track_count': 5000, 'allow_large': False}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                tool.run_public_http_diagnostic(server_factory=forbidden_server, **options)
        self.assertEqual(started, [])


if __name__ == '__main__':
    unittest.main()
