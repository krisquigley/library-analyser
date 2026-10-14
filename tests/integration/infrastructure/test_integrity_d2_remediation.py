"""Public-fixture regressions for selected graph admission and mirror draining."""
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from music_analyzer.application.use_cases.check_integrity import CheckIntegrity
from music_analyzer.infrastructure.persistence.integrity import SQLiteIntegrityScanner
from tests.integration.infrastructure.integrity_d2_public_fixture import create_public_graph_database


def check(scan, name):
    return next(item for item in scan.checks if item.check_id == name)


class ObservedCursor:
    def __init__(self, cursor, owner, mirror):
        self.cursor, self.owner, self.mirror = cursor, owner, mirror
        self.delivered = 0
        self.closed = False

    def fetchone(self):
        if self.mirror and self.delivered and self.owner.late_error:
            self.owner.injected += 1
            raise sqlite3.OperationalError('PRIVATE late mirror cursor')
        row = self.cursor.fetchone()
        if row is not None:
            self.delivered += 1
        elif self.mirror:
            self.owner.exhausted += 1
        return row

    def close(self):
        self.closed = True
        self.cursor.close()


class ObservedConnection:
    def __init__(self, connection, owner):
        self.connection, self.owner = connection, owner
        self.closed = False

    def __getattr__(self, name):
        return getattr(self.connection, name)

    def execute(self, sql, *args):
        if self.owner.cancel_at and sql.startswith(self.owner.cancel_at):
            self.owner.injected += 1
            raise KeyboardInterrupt
        # Delivery consumes paired length/value streams. Fail the actual length
        # cursor only after its first admitted mirror row, not an earlier edge
        # scan, so inequality has really been compared before the failure.
        mirror = (sql.startswith('SELECT CASE') and
                  f'FROM {self.owner.table} ORDER BY source_track_id' in sql)
        cursor = ObservedCursor(self.connection.execute(sql, *args), self.owner, mirror)
        self.owner.cursors.append(cursor)
        return cursor

    def close(self):
        self.closed = True
        self.connection.close()


class Observation:
    def __init__(self, *, late_error=False, table='graph_edges', cancel_at=None):
        self.real_connect = sqlite3.connect
        self.late_error, self.table, self.cancel_at = late_error, table, cancel_at
        self.injected = self.exhausted = 0
        self.cursors, self.connections = [], []

    def connect(self, *args, **kwargs):
        connection = ObservedConnection(self.real_connect(*args, **kwargs), self)
        self.connections.append(connection)
        return connection


class IntegrityD2Remediation(unittest.TestCase):
    def setUp(self):
        self.scratch = tempfile.TemporaryDirectory()
        self.addCleanup(self.scratch.cleanup)
        self.path = Path(self.scratch.name) / 'public.sqlite'

    def create(self, version=10):
        create_public_graph_database(self.path, version)

    def change(self, sql):
        with closing(sqlite3.connect(self.path)) as db:
            db.execute(sql)
            db.commit()

    def scan(self, observation=None):
        if observation is None:
            return SQLiteIntegrityScanner().scan(str(self.path))
        with patch('sqlite3.connect', observation.connect):
            scan = SQLiteIntegrityScanner().scan(str(self.path))
        self.assertTrue(all(cursor.closed for cursor in observation.cursors))
        self.assertTrue(all(db.closed for db in observation.connections))
        self.assertNotIn('PRIVATE', repr(scan))
        return scan

    def report(self, scan):
        class Retained:
            def scan(self, database, deadline_seconds=120):
                return scan
        return CheckIntegrity(Retained()).execute(str(self.path))

    def blocked(self, scan, owner):
        item = check(scan, owner)
        self.assertEqual((item.state, item.count, item.count_precision),
                         ('blocked', None, 'unavailable'))

    def test_healthy_public_fixture_and_real_wrapper_control(self):
        for version in range(6, 11):
            with self.subTest(version=version), tempfile.TemporaryDirectory() as td:
                self.path = Path(td) / 'public.sqlite'
                self.create(version)
                observed = Observation()
                scan = self.scan(observed)
                self.assertFalse(scan.findings)
                self.assertTrue(scan.implemented_scope_complete)
                self.assertEqual(self.report(scan).exit_code, 4)
                self.assertEqual(observed.exhausted, int(version >= 7))

    def test_real_late_error_wrapper_self_control(self):
        self.create()
        observed = Observation(late_error=True)
        with closing(observed.connect(self.path)) as db:
            cursor = db.execute('SELECT CASE typeof(score) WHEN \'real\' THEN NULL END FROM (SELECT score FROM graph_edges ORDER BY source_track_id)')
            self.assertEqual(cursor.fetchone(), (None,))
            with self.assertRaises(sqlite3.OperationalError):
                cursor.fetchone()
            cursor.close()
        self.assertEqual(observed.injected, 1)
        self.assertTrue(cursor.closed)
        self.assertTrue(db.closed)

    def test_schema_blocked_selected_graph_preserves_schema_corruption(self):
        self.create()
        self.change('CREATE TABLE unexpected_public_object(x)')
        scan = self.scan()
        self.assertEqual(scan.stop_reason, 'schema_blocked')
        for owner in ('current_graph', 'historical_graph'):
            self.blocked(scan, owner)
        report = self.report(scan)
        self.assertEqual(report.exit_code, 4)
        self.assertEqual([f.code for f in report.findings], ['schema_object_set_mismatch'])

    def test_cancel_during_core_blocks_both_graph_phases_and_preserves_exit130(self):
        self.create()
        observed = Observation(cancel_at='SELECT id,sha256,size')
        scan = self.scan(observed)
        self.assertEqual(observed.injected, 1)
        self.assertEqual(scan.stop_reason, 'cancelled')
        self.assertEqual(check(scan, 'core_rows').state, 'interrupted')
        for owner in ('current_graph', 'historical_graph'):
            self.blocked(scan, owner)
        report = self.report(scan)
        self.assertEqual(report.exit_code, 130)
        self.assertEqual([f.code for f in report.findings], ['cancelled'])

    def test_started_current_graph_interrupted_history_blocked(self):
        self.create()
        observed = Observation(cancel_at='SELECT id FROM graph_builds')
        scan = self.scan(observed)
        current = check(scan, 'current_graph')
        self.assertEqual((current.state, current.count, current.count_precision),
                         ('interrupted', 0, 'lower_bound'))
        self.blocked(scan, 'historical_graph')
        self.assertEqual(self.report(scan).exit_code, 130)

    def test_unknown_version_blocks_graph_and_preserves_unsupported(self):
        self.create()
        self.change('PRAGMA user_version=99')
        scan = self.scan()
        for owner in ('current_graph', 'historical_graph'):
            self.blocked(scan, owner)
        self.assertEqual(self.report(scan).exit_code, 3)

    def test_v6_schema_failure_retains_genuine_graph_not_applicable(self):
        self.create(6)
        self.change('CREATE TABLE unexpected_public_object(x)')
        scan = self.scan()
        for owner in ('current_graph', 'historical_graph'):
            item = check(scan, owner)
            self.assertEqual((item.state, item.count, item.count_precision),
                             ('not_applicable', None, 'unavailable'))
        self.assertEqual([f.code for f in self.report(scan).findings], ['schema_object_set_mismatch'])

    def test_mirror_inequality_survives_real_late_cursor_error(self):
        for table in ('graph_edges', 'graph_positioned_edges'):
            with self.subTest(table=table), tempfile.TemporaryDirectory() as td:
                self.path = Path(td) / 'public.sqlite'
                self.create()
                self.change(f'UPDATE {table} SET score=0.6,distance=0.4')
                observed = Observation(late_error=True, table=table)
                scan = self.scan(observed)
                self.assertEqual(observed.injected, 1)
                self.assertEqual(scan.stop_reason, 'read_error')
                self.assertEqual(check(scan, 'current_graph').state, 'interrupted')
                mirrors = [f for f in scan.findings if f.code == 'graph_mirror_invalid']
                self.assertEqual([(f.check_id, f.count, f.count_unit, f.count_precision) for f in mirrors],
                                 [('current_graph', 1, 'occurrences', 'lower_bound')])
                self.blocked(scan, 'historical_graph')
                report = self.report(scan)
                self.assertEqual(report.exit_code, 4)
                self.assertEqual([f.code for f in report.findings], ['graph_mirror_invalid', 'read_failed'])

    def test_mirror_inequalities_exhaust_and_count_once_per_relation_exactly(self):
        self.create()
        for table in ('graph_edges', 'graph_positioned_edges'):
            self.change(f'UPDATE {table} SET score=0.6,distance=0.4')
        scan = self.scan(Observation())
        mirrors = [f for f in scan.findings if f.code == 'graph_mirror_invalid']
        self.assertEqual([(f.count, f.count_precision) for f in mirrors], [(2, 'exact')])
        self.assertEqual(check(scan, 'current_graph').state, 'completed')
        self.assertEqual(check(scan, 'historical_graph').state, 'completed')

    def test_equal_first_row_late_error_does_not_invent_mirror_finding(self):
        self.create()
        observed = Observation(late_error=True)
        scan = self.scan(observed)
        self.assertEqual(observed.injected, 1)
        self.assertEqual(scan.stop_reason, 'read_error')
        self.assertFalse(any(f.code == 'graph_mirror_invalid' for f in scan.findings))
