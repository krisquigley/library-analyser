"""Duplicate full-row resource delivery is proxy-only, never persisted corruption."""
from contextlib import closing
import sqlite3
import unittest
from unittest.mock import patch

from music_analyzer.infrastructure.persistence import integrity_evidence as adapter
from music_analyzer.infrastructure.persistence.integrity import MAX_UTF8_BYTES, SQLiteIntegrityScanner
from tests.integration.infrastructure.test_integrity_evidence_identity_admission import IntegrityEvidenceIdentityAdmission
from tests.integration.infrastructure.test_integrity_d2_evidence_admission import Observation, selected, findings


class IntegrityEvidenceTailAccounting(unittest.TestCase):
    fixture = IntegrityEvidenceIdentityAdmission.fixture

    def test_source_and_healthy_firing_proxy_controls(self):
        for blob in (False, True):
            with self.subTest(blob=blob):
                path, track, run, document, identities = self.fixture(blob)
                sql = 'SELECT track_id,run_id,evidence_json FROM graph_feature_evidence WHERE track_id=? AND run_id=?'
                with closing(sqlite3.connect(path)) as db:
                    source = db.execute(sql, (track, run)).fetchone()
                    self.assertEqual(db.execute('PRAGMA integrity_check').fetchone(), ('ok',))
                    self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(), [])
                    self.assertEqual(db.execute('SELECT count(*) FROM graph_feature_evidence').fetchone(), (4,))
                for fault in (None, 'duplicate'):
                    observation = Observation(run, fault)
                    with closing(observation.connect(path)) as db:
                        with closing(db.execute(sql, (track, run))) as cursor:
                            rows = list(cursor)
                    self.assertEqual(rows, [source] * (2 if fault else 1))
                    self.assertEqual((observation.matched, observation.fired), (2, 1) if fault else (1, 0))
                    self.assertEqual(observation.cursors, observation.closed_cursors)
                    self.assertEqual(observation.closed_connections, 1)
                healthy = Observation(run)
                with patch('sqlite3.connect', healthy.connect):
                    scan = SQLiteIntegrityScanner().scan(str(path))
                self.assertTrue(scan.implemented_scope_complete)
                self.assertFalse(scan.findings)
                self.assertEqual(healthy.fired, 0)
                self.assertEqual(healthy.cursors, healthy.closed_cursors)
                self.assertEqual(healthy.closed_connections, 1)

    def duplicate_meter(self, blob, rows):
        path, track, run, document, identities = self.fixture(blob)
        row_bytes = document + identities
        remaining = row_bytes if rows == 1 else 2 * row_bytes + 100000
        self.assertGreaterEqual(remaining, row_bytes)
        if rows == 1:
            self.assertLess(remaining, 2 * row_bytes)
        observation = Observation(run, 'duplicate')
        meter = {}
        original = adapter._payload
        def payload(delivery, actual_track, actual_run, *args):
            if actual_run == run:
                meter['delivery'] = delivery
                meter['before'] = MAX_UTF8_BYTES - remaining
                delivery.utf8_bytes = meter['before']
            try:
                return original(delivery, actual_track, actual_run, *args)
            finally:
                if actual_run == run:
                    meter['charged'] = delivery.utf8_bytes - meter['before']
        with patch('sqlite3.connect', observation.connect), patch.object(adapter, '_payload', payload):
            scan = SQLiteIntegrityScanner().scan(str(path))
        self.assertEqual(observation.cursors, observation.closed_cursors)
        self.assertEqual(observation.closed_connections, 1)
        self.assertTrue(observation.handler_cleared)
        return scan, observation, meter, row_bytes

    def one_row_budget(self, blob):
        scan, observation, meter, row_bytes = self.duplicate_meter(blob, 1)
        self.assertEqual(meter['charged'], row_bytes)
        self.assertEqual(scan.stop_reason, 'utf8_limit', 'Tail full row must be re-admitted before allocation')
        self.assertEqual(observation.value_runs.count(observation.target), 1)
        self.assertEqual(observation.fired, 0, 'Queued duplicate must not be fetched without capacity')
        self.assertEqual(selected(scan, 'current_evidence').count, 1)
        self.assertEqual(selected(scan, 'current_evidence').count_precision, 'lower_bound')

    def test_text_remaining_budget_admits_one_not_two_full_rows(self):
        self.one_row_budget(False)

    def test_utf16_blob_remaining_budget_admits_one_not_two_full_rows(self):
        self.one_row_budget(True)

    def two_row_budget(self, blob):
        scan, observation, meter, row_bytes = self.duplicate_meter(blob, 2)
        self.assertEqual(meter['charged'], 2 * row_bytes, 'Both operational deliveries consume identities and decoded document bytes')
        self.assertEqual(observation.fired, 1)
        self.assertEqual(observation.value_runs.count(observation.target), 2)
        self.assertEqual(findings(scan), [('current_evidence', 'evidence_delivery_invalid', 1, 'exact')])
        self.assertEqual(selected(scan, 'current_evidence').count, 2)
        self.assertEqual(selected(scan, 'historical_evidence').count, 2)
        self.assertTrue(scan.implemented_scope_complete)

    def test_text_duplicate_recharged_without_semantic_inflation(self):
        self.two_row_budget(False)

    def test_utf16_blob_duplicate_recharged_without_semantic_inflation(self):
        self.two_row_budget(True)
