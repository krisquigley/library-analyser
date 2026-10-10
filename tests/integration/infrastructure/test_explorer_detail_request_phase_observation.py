"""PR B RED: actual request-local reader and response spans on public fixtures.

No latency targets or synthetic waterfall: inclusive validation children retain
parents and server monotonic clocks never stand in for client body/paint time.
"""
from contextlib import closing, contextmanager
import math
from pathlib import Path
import sqlite3
import unittest

from music_explorer.infrastructure.explorer_readonly import ReadOnlyExplorerSQLiteRepository
from tools.explorer_fixture_inspection import fingerprint_sqlite_files
from tools.explorer_http_diagnostic import run_public_http_diagnostic
from tools.explorer_synthetic_fixture import public_synthetic_fixture


class DetailRequestPhaseObservationTests(unittest.TestCase):
    def run_tool(self, **options):
        return run_public_http_diagnostic(sample_count=1, timeout_seconds=5, **options)

    def observations(self, report):
        self.assertTrue('server_observation' in report,
                      'PR B missing actual request-local server microprofiler evidence')
        observation = report['server_observation']
        self.assertEqual(observation['observer_mode'], 'observer_on')
        spans = observation['spans']
        self.assertTrue(spans)
        grouped = {}
        for span in spans:
            self.assertIsInstance(span['request_id'], str)
            self.assertTrue(span['request_id'])
            self.assertIsInstance(span['thread_id'], str)
            self.assertTrue(span['thread_id'])
            request = grouped.setdefault(span['request_id'], {
                'request_id': span['request_id'], 'method': span['method'],
                'route': span['route'], 'clock': span['clock'],
                'thread_id': span['thread_id'], 'spans': []})
            self.assertEqual(span['thread_id'], request['thread_id'])
            self.assertEqual(span['clock'], request['clock'])
            request['spans'].append(span)
        requests = list(grouped.values())
        for request in requests:
            self.assertEqual(request['clock'], 'monotonic')
            spans = request['spans']
            by_id = {span['span_id']: span for span in spans}
            self.assertEqual(len(by_id), len(spans))
            for span in spans:
                self.assertEqual(span['request_id'], request['request_id'])
                for key in ('start_ms', 'end_ms'):
                    self.assertIsNot(type(span[key]), bool)
                    self.assertTrue(math.isfinite(span[key]))
                self.assertGreaterEqual(span['end_ms'], span['start_ms'])
                parent = span['parent_id']
                if parent is not None:
                    self.assertIn(parent, by_id)
                    self.assertLessEqual(by_id[parent]['start_ms'], span['start_ms'])
                    self.assertGreaterEqual(by_id[parent]['end_ms'], span['end_ms'])
        return requests

    def test_post_membership_and_get_membership_selected_read_have_distinct_validation_spans(self):
        report = self.run_tool()
        self.assertEqual(report['attempted'], 1)
        self.assertEqual(report['profiles']['warm']['succeeded'], 1,
                         'tiny actual HTTP selection/detail must succeed before attribution checks')
        requests = self.observations(report)
        post = [r for r in requests if r['method'] == 'POST' and r['route'] == '/api/current']
        detail = [r for r in requests if r['method'] == 'GET' and r['route'] == '/api/tracks/:handle']
        self.assertEqual(len(post), 1)
        self.assertEqual(len(detail), 1)
        self.assertNotEqual(post[0]['request_id'], detail[0]['request_id'])
        for request, expected_validations in ((post[0], 1), (detail[0], 2)):
            spans = request['spans']
            memberships = [s for s in spans if s['phase'] == 'membership']
            self.assertEqual(len(memberships), 1)
            validations = [s for s in spans if s['phase'] == 'validation']
            self.assertEqual(len(validations), expected_validations,
                             'observation must retain every existing validated transaction')
            self.assertEqual(sum(s['parent_id'] == memberships[0]['span_id']
                                 for s in validations), 1)
            for validation in validations:
                children = {s['phase'] for s in spans
                            if s['parent_id'] == validation['span_id']}
                self.assertTrue({'validation_schema', 'validation_rows',
                                 'validation_graph', 'validation_evidence'}.issubset(children))
                self.assertEqual(validation['status'], 'ok')
        reads = [s for s in detail[0]['spans'] if s['phase'] == 'selected_read']
        self.assertEqual(len(reads), 1)
        self.assertEqual(sum(s['phase'] == 'validation' and
                             s['parent_id'] == reads[0]['span_id']
                             for s in detail[0]['spans']), 1)
        self.assertIs(report['readonly']['unchanged'], True)

        self.assert_response_scopes(requests)

    def assert_response_scopes(self, requests):
        detail = next(r for r in requests if r['route'] == '/api/tracks/:handle')
        by_phase = {s['phase']: s for s in detail['spans']}
        self.assertTrue({'stage_preflight', 'stage_decode', 'mapping', 'dto_serialization',
                         'utf8_encoding', 'socket_write'}.issubset(by_phase))
        mapping, serialization, encoding, write = (by_phase[name] for name in
            ('mapping', 'dto_serialization', 'utf8_encoding', 'socket_write'))
        preflight, decode = (by_phase[name] for name in ('stage_preflight', 'stage_decode'))
        self.assertLessEqual(preflight['end_ms'], decode['start_ms'])
        self.assertLessEqual(decode['start_ms'], decode['end_ms'])
        self.assertLessEqual(decode['end_ms'], mapping['start_ms'])
        self.assertLessEqual(mapping['end_ms'], serialization['start_ms'])
        self.assertLessEqual(serialization['end_ms'], encoding['start_ms'])
        self.assertLessEqual(encoding['end_ms'], write['start_ms'])
        self.assertEqual(encoding['bytes'], write['bytes'])
        self.assertGreater(write['bytes'], 0)
        self.assertEqual(write['status'], 'ok')
        self.assertEqual(write['scope'], 'server_socket_write_not_client_receipt')
        self.assertNotIn('browser_paint_ms', detail)

    def test_historical_failure_retains_partial_validation_and_restores_observer_on_exception(self):
        observed = {}
        original = {name: getattr(ReadOnlyExplorerSQLiteRepository, name) for name in
                    ('_connection', '_transaction', '_validate', '_validate_rows',
                     '_validate_graph_rows', '_validate_graph_feature_rows', 'track_ids', 'read_track')}

        @contextmanager
        def corrupt_fixture(**options):
            with public_synthetic_fixture(**options) as fixture:
                path = Path(fixture['db_path'])
                with closing(sqlite3.connect(path)) as db, db:
                    db.execute('UPDATE graph_feature_evidence SET fingerprint=? '
                               'WHERE rowid=(SELECT max(rowid) FROM graph_feature_evidence '
                               'WHERE is_current=0)', ('0' * 64,))
                observed['before'] = fingerprint_sqlite_files(path)
                yield fixture
                observed['after'] = fingerprint_sqlite_files(path)
                observed['path'] = path

        report = self.run_tool(fixture_factory=corrupt_fixture)
        self.assertEqual(observed['before'], observed['after'])
        self.assertFalse(observed['path'].parent.exists())
        self.assertTrue(any(r['outcome'] == 'http_error' for r in report['requests']))
        for name, method in original.items():
            self.assertIs(getattr(ReadOnlyExplorerSQLiteRepository, name), method)

        def failing_server(*args, **kwargs):
            raise RuntimeError('test-owned server setup failure')

        with self.assertRaisesRegex(RuntimeError, 'test-owned server setup failure'):
            self.run_tool(server_factory=failing_server)
        for name, method in original.items():
            self.assertIs(getattr(ReadOnlyExplorerSQLiteRepository, name), method,
                          'all process-local wrappers must restore on exceptional exit')
        requests = self.observations(report)
        spans = [s for r in requests for s in r['spans']]
        failed = [s for s in spans if s['phase'] == 'validation_evidence' and s['status'] == 'failed']
        self.assertTrue(failed, 'unrelated corrupt historical evidence must remain fail-closed')
        self.assertTrue(any(s['phase'] == 'validation_rows' and s['status'] == 'ok' for s in spans),
                        'completed earlier subphases survive the failed validation')
        self.assertFalse(any(s['phase'] == 'selected_read' for s in spans))
        self.assertIs(report['readonly']['unchanged'], True)
