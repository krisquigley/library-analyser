"""Unexpected retained EOF delivery is owner-invalid, not a driver failure."""
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from music_analyzer.infrastructure.persistence import integrity
from tests.integration.infrastructure.integrity_d3_public_fixture import create_public_retained_database


class EOFCursor:
    def __init__(self, raw, observation, target):
        self.raw, self.observation, self.target = raw, observation, target
        self.last = None
        self.fired = False

    def fetchone(self):
        row = self.raw.fetchone()
        if self.target:
            if row is not None:
                self.last = row
            elif not self.fired and self.observation.mode != 'healthy':
                self.fired = True
                self.observation.fired += 1
                if self.observation.mode == 'read_error':
                    raise sqlite3.OperationalError('public EOF read failure')
                return self.last
        return row

    def close(self):
        self.observation.closed += 1
        return self.raw.close()

    def __getattr__(self, name):
        return getattr(self.raw, name)


class EOFConnection:
    def __init__(self, raw, observation):
        self.raw, self.observation = raw, observation

    def execute(self, sql, *args):
        cursor = self.raw.execute(sql, *args)
        self.observation.opened += 1
        target = (sql.startswith('SELECT rowid,') and
                  f'FROM {self.observation.table} ORDER BY rowid' in sql)
        return EOFCursor(cursor, self.observation, target)

    def __getattr__(self, name):
        return getattr(self.raw, name)


class Observation:
    def __init__(self, table, mode):
        self.real_connect = sqlite3.connect
        self.table, self.mode = table, mode
        self.fired = self.opened = self.closed = 0

    def connect(self, *args, **kwargs):
        return EOFConnection(self.real_connect(*args, **kwargs), self)


class RetainedEOF(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='retained-eof-')
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / 'public.sqlite'
        create_public_retained_database(self.path, 6)

    def test_direct_firing_nonfiring_and_nontarget_controls(self):
        for table, columns, count in (
                ('track_metadata', 'common_json,tags_json,warnings_json', 2),
                ('stages', 'stage,result', 8)):
            for mode in ('healthy', 'duplicate'):
                with self.subTest(table=table, mode=mode):
                    observation = Observation(table, mode)
                    with closing(observation.connect(self.path)) as db:
                        cursor = db.execute(f'SELECT rowid,{columns} FROM {table} ORDER BY rowid')
                        rows = []
                        while (row := cursor.fetchone()) is not None:
                            rows.append(row)
                        self.assertIsNone(cursor.fetchone())
                        cursor.close()
                        self.assertEqual(len(rows), count + (mode == 'duplicate'))
                        if mode == 'duplicate':
                            self.assertEqual(rows[-1], rows[-2])
                        cursor = db.execute(f'SELECT count(*) FROM {table}')
                        self.assertEqual(cursor.fetchone(), (count,))
                        self.assertIsNone(cursor.fetchone())
                        cursor.close()
                    self.assertEqual(observation.fired, int(mode == 'duplicate'))
                    self.assertEqual(observation.opened, observation.closed)

    def test_healthy_wrappers_equal_unwrapped_at_shared_exact_cap(self):
        baseline = integrity.SQLiteIntegrityScanner().scan(str(self.path))
        self.assertEqual(baseline.findings, ())
        for table in ('track_metadata', 'stages'):
            for cap in (1_000_000, 217):
                with self.subTest(table=table, cap=cap):
                    observation = Observation(table, 'healthy')
                    with patch.object(integrity.sqlite3, 'connect', observation.connect), patch.object(integrity, 'MAX_ROWS', cap):
                        self.assertEqual(integrity.SQLiteIntegrityScanner().scan(str(self.path)), baseline)
                    self.assertEqual(observation.fired, 0)
                    self.assertEqual(observation.opened, observation.closed)

    def assert_eof_scan(self, table, owner, count, mode):
        for cap in (1_000_000, 217):
            with self.subTest(table=table, cap=cap, mode=mode):
                observation = Observation(table, mode)
                deliveries = []
                class ObservedDelivery(integrity.Delivery):
                    def __init__(self, *args):
                        super().__init__(*args)
                        deliveries.append(self)
                with patch.object(integrity.sqlite3, 'connect', observation.connect), patch.object(integrity, 'MAX_ROWS', cap), patch.object(integrity, 'Delivery', ObservedDelivery):
                    scan = integrity.SQLiteIntegrityScanner().scan(str(self.path))
                self.assertEqual(observation.fired, 1)
                self.assertEqual(observation.opened, observation.closed)
                result = next(c for c in scan.checks if c.check_id == owner)
                actual = [(f.check_id, f.code, f.count, f.count_precision) for f in scan.findings]
                if mode == 'read_error':
                    self.assertEqual(scan.stop_reason, 'read_error')
                    self.assertEqual((result.state, result.count, result.count_precision), ('interrupted', count, 'lower_bound'))
                    self.assertEqual(actual, [('resource_access', 'read_failed', 1, 'lower_bound')])
                    self.assertIsNotNone(deliveries[-1].first_error)
                else:
                    self.assertEqual(scan.stop_reason, 'scope_not_implemented')
                    self.assertEqual((result.state, result.count, result.count_precision), ('completed', count, 'exact'))
                    code = 'stage_delivery_invalid' if owner == 'retained_stages' else 'metadata_delivery_invalid'
                    self.assertEqual(actual, [(owner, code, 1, 'exact')])
                    self.assertIsNone(deliveries[-1].first_error)
                    self.assertEqual(deliveries[-1].count, 217)

    def test_metadata_unexpected_eof_delivery_is_owner_invalid(self):
        self.assert_eof_scan('track_metadata', 'metadata', 2, 'duplicate')

    def test_stage_unexpected_eof_delivery_is_owner_invalid(self):
        self.assert_eof_scan('stages', 'retained_stages', 8, 'duplicate')

    def test_real_eof_read_errors_remain_operational(self):
        self.assert_eof_scan('track_metadata', 'metadata', 2, 'read_error')
        self.assert_eof_scan('stages', 'retained_stages', 8, 'read_error')
