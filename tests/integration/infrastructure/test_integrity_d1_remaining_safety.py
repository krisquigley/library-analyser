"""Remaining bounded resource and direct boundary regression packet."""
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from music_analyzer.infrastructure.persistence.integrity import SQLiteIntegrityScanner
from tests.integration.infrastructure.integrity_d1_public_fixture import create_public_core_database
from tests.integration.infrastructure.test_integrity_d1_safety import ConnectObservation


class IntegrityD1RemainingSafety(unittest.TestCase):
    def test_group_cap_is_incomplete_and_keeps_first_fixed_group(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'public.sqlite'
            create_public_core_database(path, 6)
            with closing(sqlite3.connect(path)) as db:
                db.execute("UPDATE tracks SET sha256='invalid',size=-1 WHERE sha256=?", ('2' * 64,))
                db.commit()
            with patch('music_analyzer.infrastructure.persistence.integrity.MAX_GROUPS', 1, create=True):
                result = SQLiteIntegrityScanner().scan(str(path))
            self.assertEqual(result.stop_reason, 'finding_limit', 'group budget must stop selected scope')
            self.assertTrue(result.findings_truncated)
            self.assertFalse(result.implemented_scope_complete)
            self.assertEqual([(f.check_id, f.code) for f in result.findings], [('core_rows', 'track_identity_invalid')])

    def test_direct_invalid_deadline_does_not_access_target(self):
        for deadline in (0, -1, 121, float('nan'), float('inf')):
            with self.subTest(deadline=deadline), tempfile.TemporaryDirectory() as td:
                path = Path(td) / 'public.sqlite'
                create_public_core_database(path, 6)
                observation = ConnectObservation()
                caught = None
                with patch('sqlite3.connect', observation.connect):
                    try:
                        SQLiteIntegrityScanner().scan(str(path), deadline_seconds=deadline)
                    except (ValueError, OverflowError) as error:
                        caught = error
                self.assertEqual(observation.calls, [], 'invalid override must not open any target')
                self.assertIsInstance(caught, ValueError)
                self.assertEqual(str(caught), 'Invalid audit deadline')

    def test_embedded_nul_path_never_opens_truncated_target(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'public.sqlite'
            create_public_core_database(path, 6)
            observation = ConnectObservation()
            with patch('sqlite3.connect', observation.connect):
                result = SQLiteIntegrityScanner().scan(str(path) + '\x00PRIVATE')
            self.assertEqual(observation.calls, [], 'NUL path must be rejected before SQLite URI processing')
            self.assertEqual(result.stop_reason, 'unreadable_database')
            self.assertFalse(result.implemented_scope_complete)
            self.assertNotIn('PRIVATE', repr(result))

    def test_partial_schema_findings_remain_grouped_on_row_stop(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'public.sqlite'
            create_public_core_database(path, 6)
            with closing(sqlite3.connect(path)) as db:
                db.execute('ALTER TABLE runs ADD COLUMN extra TEXT')
                db.execute('ALTER TABLE stages ADD COLUMN extra TEXT')
            with patch('music_analyzer.infrastructure.persistence.integrity.MAX_ROWS', 150):
                result = SQLiteIntegrityScanner().scan(str(path))
            self.assertEqual(result.stop_reason, 'row_limit')
            keys = [(f.check_id, f.code) for f in result.findings]
            self.assertEqual(len(keys), len(set(keys)), 'late schema findings must stay fixed-code grouped')
            columns = next(f for f in result.findings if f.code == 'schema_columns_mismatch')
            self.assertEqual(columns.count, 2)
            self.assertEqual(columns.count_precision, 'lower_bound')

    def test_unexpected_object_observation_survives_late_enumeration_stop(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'public.sqlite'
            create_public_core_database(path, 6)
            with closing(sqlite3.connect(path)) as db:
                db.execute('CREATE TABLE AAA_extra(x TEXT)')
            with patch('music_analyzer.infrastructure.persistence.integrity.MAX_ROWS', 20):
                result = SQLiteIntegrityScanner().scan(str(path))
            self.assertEqual(result.stop_reason, 'row_limit')
            self.assertIn('schema_object_set_mismatch', [f.code for f in result.findings],
                          'already delivered unexpected object cannot disappear on late stop')
            unexpected = next(f for f in result.findings if f.code == 'schema_object_set_mismatch')
            self.assertEqual(unexpected.count, 1)
            self.assertEqual(unexpected.count_precision, 'lower_bound')
