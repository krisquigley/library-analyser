"""Small additional controls for the tools-only server profiler."""
import unittest
from unittest.mock import patch

from tools.explorer_http_diagnostic import run_public_http_diagnostic
from tools.explorer_http_server_observation import ServerObservation


class ServerObservationControls(unittest.TestCase):
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
        report = run_public_http_diagnostic()
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
        # The fixture has 12 tracks x 2 historical runs plus current rows;
        # all four validation transactions (summary, POST, GET twice) retain history.
        self.assertGreater(len(decoded), 12 * 4)
        self.assertFalse(any(span['status'] == 'failed' for span in spans))
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
        report = run_public_http_diagnostic(fixture_factory=corrupt_fixture)
        self.assertIs(reader.validate_graph_feature_evidence_payload, original_validator)
        self.assertIs(reader.json, original_json)
        self.assertIs(reader.ReadOnlyExplorerSQLiteRepository._iter_validated_graph_feature_rows, original_iterator)
        self.assertEqual(report['profiles']['warm']['succeeded'], 0)
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
