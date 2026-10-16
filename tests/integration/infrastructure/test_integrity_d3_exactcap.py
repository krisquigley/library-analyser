"""Regression: retained EOF proof must count rows, not per-value admission flags."""
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
from time import monotonic
import unittest
from unittest.mock import patch

from music_analyzer.infrastructure.persistence import integrity
from music_analyzer.infrastructure.persistence.integrity_retained import scan_retained
from tests.integration.infrastructure.integrity_d3_public_fixture import create_public_retained_database


class RetainedExactCap(unittest.TestCase):
    def test_three_metadata_rows_exact_eof_and_one_below(self):
        with closing(sqlite3.connect(':memory:')) as db:
            db.execute('CREATE TABLE track_metadata(common_json,tags_json,warnings_json)')
            db.executemany('INSERT INTO track_metadata VALUES(?,?,?)', [('[]', '[]', '[]')] * 3)
            self.assertEqual(db.execute('SELECT * FROM track_metadata').fetchall(),
                             [('[]', '[]', '[]')] * 3)
            for cap in (7, 6, 5):
                with self.subTest(cap=cap):
                    delivery = integrity.Delivery(db, monotonic() + 10)
                    with patch.object(integrity, 'MAX_ROWS', cap):
                        if cap == 5:
                            with self.assertRaises(integrity.AdmissionStop) as caught:
                                scan_retained(delivery, 'metadata')
                            self.assertEqual(caught.exception.reason, 'row_limit')
                            self.assertEqual(delivery.retained_work['metadata'], 2)
                        else:
                            try:
                                result, findings = scan_retained(delivery, 'metadata')
                            except integrity.AdmissionStop as error:
                                self.fail(f'Proven EOF at cap {cap} must complete, not stop: {error.reason}')
                            self.assertEqual((result.state, result.count, result.count_precision),
                                             ('completed', 3, 'exact'))
                            self.assertEqual(findings, ())
                    self.assertEqual(delivery.count, min(cap, 6))

    def test_public_v6_exact_eof_preserves_precise_retained_completion(self):
        deliveries = []
        class Observed(integrity.Delivery):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                deliveries.append(self)
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'public.sqlite'
            create_public_retained_database(path, 6)
            with closing(sqlite3.connect(path)) as db:
                self.assertEqual(db.execute('SELECT count(*) FROM stages').fetchone(), (8,))
            with patch.object(integrity, 'Delivery', Observed):
                baseline = integrity.SQLiteIntegrityScanner().scan(str(path))
                # The retained prefix remains exactly217; sole physical ok
                # contributes one additional shared-meter delivery afterward.
                self.assertEqual(deliveries[-1].count, 218)
                self.assertEqual(deliveries[-1].count - deliveries[-1].sqlite_work['sqlite_physical'], 217)
                self.assertEqual(baseline.stop_reason, 'completed')
                for cap in (218, 217, 216):
                    with self.subTest(cap=cap), patch.object(integrity, 'MAX_ROWS', cap):
                        scan = integrity.SQLiteIntegrityScanner().scan(str(path))
                        result = next(c for c in scan.checks if c.check_id == 'retained_stages')
                        expected = ('interrupted', 7, 'lower_bound') if cap == 216 else ('completed', 8, 'exact')
                        self.assertEqual((result.state, result.count, result.count_precision), expected)
                        self.assertEqual(scan.stop_reason, 'completed' if cap == 218 else 'row_limit')
                        self.assertEqual(deliveries[-1].count, min(cap, 218))
                        physical = next(c for c in scan.checks if c.check_id == 'sqlite_physical')
                        foreign_keys = next(c for c in scan.checks if c.check_id == 'sqlite_foreign_keys')
                        if cap == 218:
                            self.assertEqual((physical.state, physical.count, physical.count_precision),
                                             ('completed', 1, 'exact'))
                            self.assertEqual((foreign_keys.state, foreign_keys.count, foreign_keys.count_precision),
                                             ('completed', 0, 'exact'))
                        else:
                            self.assertEqual((physical.state, physical.count, physical.count_precision),
                                             ('interrupted', 0, 'lower_bound') if cap == 217
                                             else ('blocked', None, 'unavailable'))
                            self.assertEqual((foreign_keys.state, foreign_keys.count, foreign_keys.count_precision),
                                             ('blocked', None, 'unavailable'))
                            self.assertFalse(scan.implemented_scope_complete)
