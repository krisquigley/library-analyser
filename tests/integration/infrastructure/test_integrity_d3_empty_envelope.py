"""Synthetic public-v6 empty envelope faults retain prior exact phase evidence."""
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from music_analyzer.application.use_cases.check_integrity import CheckIntegrity
from music_analyzer.infrastructure.persistence import integrity
from tests.integration.infrastructure.integrity_d3_public_fixture import create_public_retained_database

OWNERS = (('track_metadata', 'metadata', 3), ('stages', 'retained_stages', 8))


class Observation:
    def __init__(self, table, mode, position):
        self.connect_raw = sqlite3.connect
        self.table, self.mode, self.position = table, mode, position
        self.opened = self.closed = self.fired = self.envelopes = self.values = 0

    def connect(self, *args, **kwargs):
        raw = self.connect_raw(*args, **kwargs)
        observed = self

        class Connection:
            def execute(self, sql, *params):
                cursor = raw.execute(sql, *params)
                observed.opened += 1
                envelope = sql.startswith('SELECT CASE typeof(') and f' FROM {observed.table} ORDER BY rowid' in sql
                value = sql.startswith('SELECT rowid,') and f' FROM {observed.table} ORDER BY rowid' in sql

                class Cursor:
                    def fetchone(self):
                        row = cursor.fetchone()
                        if envelope and row is not None:
                            observed.envelopes += 1
                            if observed.envelopes == observed.position and observed.mode != 'healthy':
                                observed.fired += 1
                                if observed.mode == 'driver':
                                    cursor.close()
                                    return cursor.fetchone()  # genuine sqlite3 ProgrammingError
                                return () if observed.mode == 'empty' else row[-1:]
                        if value and row is not None:
                            observed.values += 1
                        return row

                    def close(self):
                        observed.closed += 1
                        return cursor.close()

                    def __getattr__(self, name):
                        return getattr(cursor, name)
                return Cursor()

            def __getattr__(self, name):
                return getattr(raw, name)
        return Connection()


class EmptyRetainedEnvelope(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / 'public.sqlite'
        create_public_retained_database(self.path, 6)
        with closing(sqlite3.connect(self.path)) as db:
            db.execute('INSERT INTO tracks VALUES(?,?,?)', ('sha256:' + '3' * 64, '3' * 64, 103))
            db.execute('INSERT INTO track_audio VALUES(?,?,?,?,?)', ('sha256:' + '3' * 64, 183., 'mutagen', 'eligible', ''))
            db.execute('INSERT INTO track_metadata VALUES(?,?,?,?)', ('sha256:' + '3' * 64, '[]', '[]', '[]'))
            db.commit()

    def scan(self, table, mode, position, application=False):
        observed = Observation(table, mode, position)
        with patch.object(integrity.sqlite3, 'connect', observed.connect):
            scanner = integrity.SQLiteIntegrityScanner()
            result = CheckIntegrity(scanner).execute(str(self.path)) if application else scanner.scan(str(self.path))
        self.assertEqual(observed.opened, observed.closed)
        self.assertEqual(observed.fired, int(mode != 'healthy'))
        return result, observed

    def test_direct_firing_and_nontarget_controls(self):
        for table, owner, count in OWNERS:
            for position in (1, (count + 1) // 2, count):
                for mode in ('healthy', 'short', 'empty'):
                    with self.subTest(table=table, mode=mode, position=position):
                        observed = Observation(table, mode, position)
                        column = 'result' if table == 'stages' else 'common_json'
                        with closing(observed.connect(self.path)) as db:
                            cursor = db.execute(f'SELECT CASE typeof({column}) WHEN \'text\' THEN 1 ELSE 0 END,rowid,count(*) OVER() FROM {table} ORDER BY rowid')
                            rows = list(iter(cursor.fetchone, None))
                            cursor.close()
                            cursor = db.execute(f'SELECT count(*) FROM {table}')
                            self.assertEqual(cursor.fetchone(), (count,))
                            cursor.close()
                        self.assertEqual(len(rows), count)
                        self.assertEqual(len(rows[position - 1]), {'healthy': 3, 'short': 1, 'empty': 0}[mode])
                        self.assertEqual(observed.fired, int(mode != 'healthy'))
                        self.assertEqual(observed.opened, observed.closed)

    def test_healthy_wrapper_transparent(self):
        plain = integrity.SQLiteIntegrityScanner().scan(str(self.path))
        self.assertEqual(plain.findings, ())
        for table, owner, count in OWNERS:
            result, observed = self.scan(table, 'healthy', 1)
            self.assertEqual(result, plain)
            self.assertEqual((observed.envelopes, observed.values), (count, count))

    def test_nonempty_short_envelopes_remain_owner_invalid(self):
        for table, owner, count in OWNERS:
            for position in (1, (count + 1) // 2, count):
                with self.subTest(owner=owner, position=position):
                    result, observed = self.scan(table, 'short', position)
                    check = next(c for c in result.checks if c.check_id == owner)
                    self.assertEqual((check.state, check.count, check.count_precision), ('completed', count, 'exact'))
                    self.assertEqual(observed.values, position - 1)
                    self.assertEqual([(f.check_id, f.code, f.count) for f in result.findings],
                                     [(owner, ('stage' if owner == 'retained_stages' else 'metadata') + '_delivery_invalid', count - position + 1)])

    def assert_operational(self, mode):
        for table, owner, count in OWNERS:
            for position in (1, (count + 1) // 2, count):
                with self.subTest(owner=owner, position=position, mode=mode):
                    result, observed = self.scan(table, mode, position)
                    self.assertEqual(result.stop_reason, 'read_error')
                    check = next(c for c in result.checks if c.check_id == owner)
                    self.assertEqual((check.state, check.count, check.count_precision), ('interrupted', position - 1, 'lower_bound'))
                    self.assertEqual((observed.envelopes, observed.values), (position, position - 1))
                    self.assertEqual([(f.check_id, f.code) for f in result.findings], [('resource_access', 'read_failed')])

    def test_empty_envelopes_stop_without_invented_cardinality_or_catchup(self):
        self.assert_operational('empty')

    def test_genuine_driver_errors_remain_operational(self):
        self.assert_operational('driver')

    def test_late_empty_stage_preserves_completed_metadata_through_application(self):
        with closing(sqlite3.connect(self.path)) as db:
            db.execute("UPDATE track_metadata SET common_json='{' WHERE rowid=1")
            db.commit()
        result, observed = self.scan('stages', 'empty', 4, application=True)
        self.assertEqual((result.schema_version, result.stop_reason, result.exit_code), (6, 'read_error', 4))
        metadata = next(c for c in result.checks if c.check_id == 'metadata')
        self.assertEqual((metadata.state, metadata.count, metadata.count_precision), ('completed', 3, 'exact'))
        self.assertIn(('metadata', 'metadata_json_invalid', 1, 'exact'),
                      [(f.check_id, f.code, f.count, f.count_precision) for f in result.findings])
        self.assertEqual((observed.envelopes, observed.values), (4, 3))
