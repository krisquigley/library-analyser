"""Whole-scanner BLOB decoded-document accounting regression."""
from pathlib import Path
import json
import tempfile
import unittest
from unittest.mock import patch

from music_analyzer.infrastructure.persistence.integrity import Delivery, SQLiteIntegrityScanner
from tests.integration.infrastructure.integrity_d2_evidence_public_fixture import (
    create_public_evidence_database, payload, canonical, store_payload, OLD_RUNS,
)


class IntegrityEvidenceBlobBudget(unittest.TestCase):
    def test_blob_fragment_and_full_delivery_both_charge_decoded_utf8(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'public.sqlite'
            ids = create_public_evidence_database(path, 10)
            value = payload(ids[0], OLD_RUNS[0])
            value['features']['bpm']['uncertainty'] = '尾' * 100
            text = canonical(value)
            expected = len(text.encode('utf-8'))
            store_payload(path, OLD_RUNS[0], value, text=text.encode('utf-16'))
            meters = []
            observations = []

            class Metered(Delivery):
                def __init__(self, *args):
                    super().__init__(*args)
                    self.before_full = None
                    meters.append(self)

                def execute(self, sql, params=()):
                    if (sql.startswith('SELECT track_id,run_id,evidence_json FROM graph_feature_evidence')
                            and params == (ids[0], OLD_RUNS[0])):
                        self.before_full = self.utf8_bytes
                    return super().execute(sql, params)

            original_loads = json.loads

            def loads(raw, *args, **kwargs):
                result = original_loads(raw, *args, **kwargs)
                if isinstance(raw, bytes) and isinstance(result, dict) and result.get('run_id') == OLD_RUNS[0]:
                    observations.append(meters[-1].utf8_bytes - meters[-1].before_full)
                return result

            def scan():
                with patch('music_analyzer.infrastructure.persistence.integrity.Delivery', Metered), patch('json.loads', loads):
                    return SQLiteIntegrityScanner().scan(str(path))

            healthy = scan()
            self.assertTrue(healthy.implemented_scope_complete)
            self.assertFalse(healthy.findings)
            self.assertEqual(observations, [expected], 'Full decoded BLOB must charge after already-charged fragments')
            boundary = meters[0].before_full
            observations.clear()
            # Leave room for all prior phases, envelopes and fragments, but one
            # byte too little for the independently measured full document.
            with patch('music_analyzer.infrastructure.persistence.integrity.MAX_UTF8_BYTES', boundary + expected - 1):
                limited = scan()
            self.assertEqual(limited.stop_reason, 'utf8_limit')
            self.assertFalse(limited.implemented_scope_complete)
            checks = {c.check_id: c for c in limited.checks}
            self.assertEqual(checks['current_evidence'].state, 'completed')
            self.assertEqual((checks['historical_evidence'].state, checks['historical_evidence'].count_precision),
                             ('interrupted', 'lower_bound'))
            self.assertIn('utf8_limit_reached', [f.code for f in limited.findings])
            self.assertFalse(observations, 'Budget stop must precede JSON decoding')
