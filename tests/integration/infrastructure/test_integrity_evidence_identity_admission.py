"""Metered genuine v10 full-row admission; not a natural 1GiB workload claim."""
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from music_analyzer.infrastructure.persistence import integrity_evidence as adapter
from music_analyzer.infrastructure.persistence.integrity import MAX_UTF8_BYTES, SQLiteIntegrityScanner
from tests.integration.infrastructure.integrity_d2_evidence_public_fixture import (
    CURRENT_RUNS, canonical, create_public_evidence_database, payload, store_payload,
)
from tests.integration.infrastructure.test_integrity_d2_evidence_admission import Observation


class IntegrityEvidenceIdentityAdmission(unittest.TestCase):
    def fixture(self, blob=False):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        path = Path(temporary.name) / 'public.sqlite'
        track = create_public_evidence_database(path)[0]
        run = CURRENT_RUNS[0]
        value = payload(track, run)
        document = canonical(value)
        if blob:
            store_payload(path, run, value, text=document.encode('utf-16'))
        with closing(sqlite3.connect(path)) as db:
            delivered = db.execute('SELECT track_id,run_id,evidence_json FROM graph_feature_evidence WHERE run_id=?', (run,)).fetchone()
        self.assertEqual(delivered[:2], (track, run))
        self.assertIsInstance(delivered[2], bytes if blob else str)
        document_size = len(document.encode('utf-8'))
        identity_size = sum(len(item.encode('utf-8')) for item in (track, run))
        self.assertGreater(identity_size, 0)
        return path, track, run, document_size, identity_size

    def metered(self, path, run, remaining):
        observation = Observation(target=run)
        original_payload = adapter._payload
        original_classify = adapter.classify_payload
        meter = {}

        def full_payload(delivery, track, actual_run, *args):
            if actual_run == run:
                self.assertNotIn('delivery', meter)
                meter['delivery'] = delivery
                meter['before'] = MAX_UTF8_BYTES - remaining
                # Explicit boundary proxy, after real decoded-domain preflight,
                # before admission or request of the repeated full row.
                delivery.utf8_bytes = meter['before']
            return original_payload(delivery, track, actual_run, *args)

        def classify(track, actual_run, digest, value):
            if actual_run == run:
                meter['charged'] = meter['delivery'].utf8_bytes - meter['before']
                meter['parsed'] = value
            return original_classify(track, actual_run, digest, value)

        with patch('sqlite3.connect', observation.connect), patch.object(adapter, '_payload', full_payload), patch.object(adapter, 'classify_payload', classify):
            scan = SQLiteIntegrityScanner().scan(str(path))
        self.assertIn('delivery', meter, 'real preflight must reach full-row admission')
        self.assertEqual(observation.cursors, observation.closed_cursors)
        self.assertEqual(observation.closed_connections, 1)
        return scan, observation, meter

    def test_healthy_scanner_without_metering(self):
        path, _, _, _, _ = self.fixture()
        scan = SQLiteIntegrityScanner().scan(str(path))
        self.assertTrue(scan.implemented_scope_complete)
        self.assertFalse(scan.findings)

    def test_exact_document_budget_refuses_text_before_full_fetch(self):
        path, _, run, document, identities = self.fixture()
        scan, observed, meter = self.metered(path, run, document)
        self.assertNotIn(run, observed.value_runs)
        self.assertNotIn('parsed', meter)
        self.assertEqual(meter['delivery'].utf8_bytes, meter['before'])
        self.assertEqual(scan.stop_reason, 'utf8_limit')

    def test_exact_full_row_budget_charges_repeated_text_identities(self):
        path, track, run, document, identities = self.fixture()
        _, observed, meter = self.metered(path, run, document + identities)
        self.assertIn(run, observed.value_runs)
        self.assertEqual(meter['parsed'], payload(track, run))
        self.assertEqual(meter['charged'], document + identities)

    def test_nontrigger_budget_charges_same_full_row(self):
        path, track, run, document, identities = self.fixture()
        _, observed, meter = self.metered(path, run, document + identities + 100000)
        self.assertIn(run, observed.value_runs)
        self.assertEqual(meter['parsed'], payload(track, run))
        self.assertEqual(meter['charged'], document + identities)

    def test_exact_document_budget_refuses_blob_before_full_fetch(self):
        path, _, run, document, identities = self.fixture(blob=True)
        scan, observed, meter = self.metered(path, run, document)
        self.assertNotIn(run, observed.value_runs)
        self.assertNotIn('parsed', meter)
        self.assertEqual(scan.stop_reason, 'utf8_limit')

    def test_exact_full_row_budget_charges_decoded_blob_and_identities(self):
        path, track, run, document, identities = self.fixture(blob=True)
        _, observed, meter = self.metered(path, run, document + identities)
        self.assertIn(run, observed.value_runs)
        self.assertEqual(meter['parsed'], payload(track, run))
        self.assertEqual(meter['charged'], document + identities)
