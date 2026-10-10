"""PR4c red contracts: tiny generated data, real loopback HTTP, no private target.

The missing opt-in harness is checked inside each test, so baseline collection
still succeeds. These tests intentionally do not implement the harness or claim
browser/render/latency-budget evidence.
"""
import importlib
import importlib.util
import json
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

    def factory(self, *, reject_current=False, stall_state=False):
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
                if stall_state:
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
