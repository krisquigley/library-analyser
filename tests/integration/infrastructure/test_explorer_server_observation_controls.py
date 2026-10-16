"""Small additional controls for the tools-only server profiler."""
import unittest
from unittest.mock import patch

from tools.explorer_http_diagnostic import run_public_http_diagnostic
from tools.explorer_http_server_observation import ServerObservation


class ServerObservationControls(unittest.TestCase):
    def _diagnostic_with_full_graph(self, **options):
        from tools.explorer_http_diagnostic import _request, _sample
        graph_outcomes = []

        def sample_then_graph(base, timeout, requests, intervals, token):
            sample = _sample(base, timeout, requests, intervals, token)
            self.assertEqual(sample['outcome'], 'ok')
            # Observe retained FULL history validation explicitly, not as an
            # accidental side effect of ordinary summary/selection/detail.
            _, outcome = _request(base, '/api/mood-axis-graph?contract=v3', 'GET',
                                  timeout, requests, intervals, 'get_graph')
            graph_outcomes.append(outcome)
            return sample

        with patch('tools.explorer_http_diagnostic._sample', side_effect=sample_then_graph):
            report = run_public_http_diagnostic(**options)
        ordinary = [span for span in report['server_observation']['spans']
                    if span['route'] != '/api/mood-axis-graph']
        self.assertTrue(ordinary)
        self.assertFalse(any(span['phase'].startswith('validation_evidence') for span in ordinary))
        self.assertEqual(report['profiles']['warm']['succeeded'], 1)
        return report, graph_outcomes

    def test_observer_off_runs_actual_http_without_installing_wrappers(self):
        with patch.object(ServerObservation, 'installed', side_effect=AssertionError('off installed observer')):
            report = run_public_http_diagnostic(observer_mode='observer_off')
        self.assertEqual(report['profiles']['warm']['succeeded'], 1)
        self.assertEqual(report['server_observation']['observer_mode'], 'observer_off')
        self.assertEqual(report['server_observation']['spans'], [])
        self.assertTrue(report['readonly']['unchanged'])

    def test_request_correlation_uses_opaque_id_not_completion_order(self):
        observer = ServerObservation()
        observer.requests = [dict(request_id='second', method='GET', route='/api/state', spans=[{'span_id': 'b'}]),
                             dict(request_id='first', method='GET', route='/api/state', spans=[{'span_id': 'a'}])]
        requests = [dict(request_id='first', method='GET', url='http://127.0.0.1/api/state'),
                    dict(request_id='second', method='GET', url='http://127.0.0.1/api/state')]
        observer.attach(requests, 'observer_on')
        self.assertEqual(requests[0]['server_spans'], [{'span_id': 'a'}])
        self.assertEqual(requests[1]['server_spans'], [{'span_id': 'b'}])

    def test_all_historical_evidence_subphases_are_observed_and_restored(self):
        from music_explorer.infrastructure import explorer_readonly as reader
        original_json = reader.json
        original_payload = reader.validate_graph_feature_evidence_payload
        original_iterator = reader.ReadOnlyExplorerSQLiteRepository._iter_validated_graph_feature_rows
        report, graph_outcomes = self._diagnostic_with_full_graph()
        self.assertEqual(graph_outcomes, ['ok'])
        self.assertIs(reader.json, original_json)
        self.assertIs(reader.validate_graph_feature_evidence_payload, original_payload)
        self.assertIs(reader.ReadOnlyExplorerSQLiteRepository._iter_validated_graph_feature_rows, original_iterator)
        spans = report['server_observation']['spans']
        phases = {span['phase'] for span in spans}
        self.assertTrue({'validation_evidence_preflight', 'validation_evidence_fetch',
                         'validation_evidence_decode', 'validation_evidence_payload'}.issubset(phases))
        decoded = [span for span in spans if span['phase'] == 'validation_evidence_decode']
        validated = [span for span in spans if span['phase'] == 'validation_evidence_payload']
        self.assertEqual(len(decoded), len(validated))
        # One retained FULL graph transaction validates every physical evidence
        # row: 11 eligible tracks x 2 runs (current plus historical), not four
        # ordinary-read global audits. Use the fixture's actual row inventory.
        counts = report['fixture_manifest']['counts']
        expected = counts['current_graph_feature_evidence'] + counts['historical_graph_feature_evidence']
        self.assertEqual(expected, 22)
        self.assertEqual(len(decoded), expected)
        self.assertFalse(any(span['status'] == 'failed' for span in spans))
        self.assertTrue(report['readonly']['unchanged'])
        self.assertNotIn('Uninstrumented', report['phases']['validation']['reason'])

    def test_evidence_observers_restore_after_payload_validation_failure(self):
        from music_explorer.infrastructure import explorer_readonly as reader
        original_json = reader.json
        original_iterator = reader.ReadOnlyExplorerSQLiteRepository._iter_validated_graph_feature_rows
        from contextlib import contextmanager, closing
        import sqlite3
        from tools.explorer_synthetic_fixture import public_synthetic_fixture
        original_validator = reader.validate_graph_feature_evidence_payload
        @contextmanager
        def corrupt_fixture(**options):
            with public_synthetic_fixture(**options) as fixture:
                with closing(sqlite3.connect(fixture['db_path'])) as db, db:
                    db.execute('UPDATE graph_feature_evidence SET fingerprint=? '
                               'WHERE rowid=(SELECT max(rowid) FROM graph_feature_evidence '
                               'WHERE is_current=0)', ('0' * 64,))
                yield fixture
        report, graph_outcomes = self._diagnostic_with_full_graph(fixture_factory=corrupt_fixture)
        self.assertEqual(graph_outcomes, ['http_error'])
        self.assertIs(reader.validate_graph_feature_evidence_payload, original_validator)
        self.assertIs(reader.json, original_json)
        self.assertIs(reader.ReadOnlyExplorerSQLiteRepository._iter_validated_graph_feature_rows, original_iterator)
        self.assertEqual(report['profiles']['warm']['succeeded'], 1)
        self.assertTrue(any(span['phase'] == 'validation_evidence_payload'
                            and span['status'] == 'failed'
                            for span in report['server_observation']['spans']))
        self.assertTrue(report['readonly']['unchanged'])

    def test_failed_socket_write_does_not_claim_attempted_body_as_written(self):
        from types import SimpleNamespace
        class FailingSocket:
            def write(self, data):
                raise OSError('test-owned socket rejection')
        class Handler:
            wfile = FailingSocket()
            def send_response(self, status):
                pass
            def send_header(self, name, value):
                pass
            def end_headers(self):
                pass
        from music_explorer.infrastructure import explorer_readonly as reader
        original_json = reader.json
        original_validate = reader.ReadOnlyExplorerSQLiteRepository._validate
        observer = ServerObservation()
        server = observer.instrument_server(SimpleNamespace(RequestHandlerClass=Handler))
        observer.local.context = dict(request_id='owned', spans=[], stack=[])
        with observer.installed():
            with self.assertRaises(OSError):
                server.RequestHandlerClass()._json({'public': True})
        self.assertIs(reader.json, original_json)
        self.assertIs(reader.ReadOnlyExplorerSQLiteRepository._validate, original_validate)
        spans = observer.local.context['spans']
        write = next(span for span in spans if span['phase'] == 'socket_write')
        self.assertEqual(write['status'], 'failed')
        self.assertIsNone(write.get('bytes'))
        self.assertEqual(write['scope'], 'server_socket_write_not_client_receipt')
        encoding = next(span for span in spans if span['phase'] == 'utf8_encoding')
        self.assertGreater(encoding['bytes'], 0)

    def test_unknown_observer_mode_is_rejected_before_fixture_creation(self):
        with patch('tools.explorer_http_diagnostic.public_synthetic_fixture'):
            with self.assertRaises(ValueError):
                run_public_http_diagnostic(observer_mode='unknown')
