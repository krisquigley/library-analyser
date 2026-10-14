"""D2a tests-only RED: current publication and all retained graph history.

Public SQLite fixtures live at the infrastructure boundary. No FULL-reader
policy changes, topology, evidence diagnostic assertions, or certification.
Controls must be executed before the desired-behavior packet.
"""
from contextlib import closing
from pathlib import Path
import re
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from music_analyzer.application.use_cases.check_integrity import CheckIntegrity
from music_analyzer.infrastructure.persistence.integrity import SQLiteIntegrityScanner
from music_analyzer.infrastructure.persistence.explorer_readonly import ReadOnlyExplorerSQLiteRepository as AnalyzerReader
from music_explorer.infrastructure.explorer_readonly import ReadOnlyExplorerSQLiteRepository as StandaloneReader
from tests.integration.infrastructure.integrity_d2_public_fixture import (
    create_public_graph_database, OLD_BUILD, CURRENT_BUILD,
)


def check(scan, name):
    return next(item for item in scan.checks if item.check_id == name)


def change(path, sql, args=()):
    with closing(sqlite3.connect(path)) as db:
        db.execute('PRAGMA foreign_keys=ON')
        db.execute(sql, args)
        db.commit()


class GraphCursor:
    """Real fetchone cursor: reject bulk graph materialization; fail after bad row."""
    def __init__(self, cursor, owner, graph):
        self.cursor, self.owner, self.graph = cursor, owner, graph
        self.bad_delivered = False
        self.close_attempts = 0

    def fetchone(self):
        if self.graph and self.bad_delivered and self.owner.late_error:
            self.owner.injected += 1
            raise sqlite3.OperationalError('PRIVATE graph cursor detail')
        row = self.cursor.fetchone()
        if row is not None:
            self.owner.delivered += 1
            if self.graph:
                self.owner.graph_rows += 1
                if self.owner.barrier is not None:
                    callback, self.owner.barrier = self.owner.barrier, None
                    callback()
                # Only the real value stream containing the old bad full edge;
                # length/type preflights and descriptor/mirror rows cannot fire.
                self.bad_delivered = OLD_BUILD in row and 0.75 in row and 0.5 in row
        return row

    def fetchall(self):
        if self.graph:
            raise AssertionError('Graph scans must stream, never fetchall')
        return self.cursor.fetchall()

    def fetchmany(self, *args):
        if self.graph:
            raise AssertionError('Graph scans must stream, never fetchmany')
        return self.cursor.fetchmany(*args)

    def __iter__(self):
        while (row := self.fetchone()) is not None:
            yield row

    def close(self):
        self.close_attempts += 1
        self.cursor.close()


class GraphConnection:
    def __init__(self, connection, owner):
        self.connection, self.owner = connection, owner
        self.closed = False
        self.rollback_attempts = 0

    def __getattr__(self, name):
        return getattr(self.connection, name)

    def execute(self, sql, *args):
        graph = bool(re.search(r'\b(?:FROM|JOIN)\s+graph_(?:builds|build_edges|build_positioned_edges|build_positioned_snapshots|edges|positioned_edges)\b', sql, re.I))
        cursor = GraphCursor(self.connection.execute(sql, *args), self.owner, graph)
        self.owner.cursors.append(cursor)
        return cursor

    def rollback(self):
        self.rollback_attempts += 1
        return self.connection.rollback()

    def close(self):
        self.closed = True
        return self.connection.close()


class GraphObservation:
    def __init__(self, *, late_error=False, barrier=None):
        self.real_connect = sqlite3.connect
        self.late_error, self.barrier = late_error, barrier
        self.connections, self.cursors = [], []
        self.injected = self.delivered = self.graph_rows = 0

    def connect(self, database, **kwargs):
        connection = GraphConnection(self.real_connect(database, **kwargs), self)
        self.connections.append(connection)
        return connection


class IntegrityD2GraphControls(unittest.TestCase):
    def test_true_versions_core_physical_fk_and_full_readers(self):
        for version in range(6, 11):
            with self.subTest(version=version), tempfile.TemporaryDirectory() as td:
                path = Path(td) / 'public.sqlite'
                identities = create_public_graph_database(path, version)
                with closing(sqlite3.connect(path)) as db:
                    self.assertEqual(db.execute('PRAGMA user_version').fetchone(), (version,))
                    self.assertEqual(db.execute('PRAGMA integrity_check(101)').fetchall(), [('ok',)])
                    self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(), [])
                    if version >= 7:
                        columns = [row[1] for row in db.execute('PRAGMA table_info(graph_builds)')]
                        self.assertEqual('source_revision' in columns, version == 10)
                        self.assertEqual(db.execute('SELECT count(*) FROM graph_build_edges').fetchone(), (2,))
                scan = SQLiteIntegrityScanner().scan(str(path))
                for name in ('compatibility', 'schema', 'core_rows'):
                    self.assertEqual(check(scan, name).state, 'completed')
                self.assertFalse(scan.findings)
                before = path.read_bytes()
                for reader_type in (AnalyzerReader, StandaloneReader):
                    reader = reader_type(str(path))
                    self.assertEqual(reader.metadata()['schema_version'], version)
                    self.assertEqual(reader.track_ids(), identities)
                    self.assertEqual(path.read_bytes(), before)

    def test_real_wrapper_healthy_and_late_error_self_control(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'public.sqlite'
            create_public_graph_database(path)
            observation = GraphObservation()
            with patch('sqlite3.connect', observation.connect):
                scan = SQLiteIntegrityScanner().scan(str(path))
            self.assertTrue(scan.implemented_scope_complete)
            self.assertTrue(all(db.closed for db in observation.connections))
            change(path, 'UPDATE graph_build_edges SET distance=0.5 WHERE build_id=?', (OLD_BUILD,))
            for fail in (False, True):
                observed = GraphObservation(late_error=fail)
                with closing(observed.connect(path.as_uri() + '?mode=ro', uri=True)) as db:
                    cursor = db.execute('SELECT build_id,score,distance FROM graph_build_edges WHERE build_id=?', (OLD_BUILD,))
                    self.assertEqual(cursor.fetchone(), (OLD_BUILD, 0.75, 0.5))
                    if fail:
                        with self.assertRaises(sqlite3.OperationalError):
                            cursor.fetchone()
                    else:
                        self.assertIsNone(cursor.fetchone())
                    cursor.close()
                self.assertEqual(observed.injected, int(fail))
                self.assertEqual(cursor.close_attempts, 1)
                self.assertTrue(db.closed)

    def test_real_graph_wal_barrier_pins_old_snapshot_with_two_connections(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'public.sqlite'
            create_public_graph_database(path)
            with closing(sqlite3.connect(path)) as db:
                self.assertEqual(db.execute('PRAGMA journal_mode=WAL').fetchone(), ('wal',))
            observed = GraphObservation()
            commits = []
            def commit():
                with closing(observed.real_connect(path, timeout=1)) as writer:
                    writer.execute('UPDATE graph_builds SET edge_count=2 WHERE id=?', (OLD_BUILD,))
                    writer.commit()
                commits.append(True)
            observed.barrier = commit
            with closing(observed.connect(path.as_uri() + '?mode=ro', uri=True)) as reader:
                reader.execute('BEGIN').close()
                cursor = reader.execute('SELECT edge_count FROM graph_builds WHERE id=?', (OLD_BUILD,))
                self.assertEqual(cursor.fetchone(), (1,))
                cursor.close()
                cursor = reader.execute('SELECT edge_count FROM graph_builds WHERE id=?', (OLD_BUILD,))
                self.assertEqual(cursor.fetchone(), (1,))
                cursor.close()
            self.assertEqual(commits, [True])
            with closing(sqlite3.connect(path)) as db:
                self.assertEqual(db.execute('SELECT edge_count FROM graph_builds WHERE id=?', (OLD_BUILD,)).fetchone(), (2,))
            self.assertTrue(all(c.close_attempts == 1 for c in observed.cursors))
            self.assertTrue(reader.closed)

    def test_v6_graph_is_genuine_not_applicable(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'public.sqlite'
            create_public_graph_database(path, 6)
            report = CheckIntegrity(SQLiteIntegrityScanner()).execute(str(path))
            for name in ('current_graph', 'historical_graph'):
                self.assertEqual(check(report, name).state, 'not_applicable')
                self.assertIsNone(check(report, name).count)
            self.assertEqual(report.exit_code, 4)
            self.assertFalse(report.complete)


class IntegrityD2Graph(unittest.TestCase):
    def completed(self, scan, name, count):
        item = check(scan, name)
        self.assertEqual(item.state, 'completed', f'{name} must exhaust populated D2a graph work')
        self.assertEqual((item.count, item.count_unit, item.count_precision), (count, 'rows', 'exact'))

    def findings(self, scan, owner, code):
        actual = [(f.check_id, f.code, f.severity, f.count, f.count_unit, f.count_precision)
                  for f in scan.findings if f.check_id in ('current_graph', 'historical_graph')]
        self.assertEqual(actual, [(owner, code, 'corruption', 1, 'occurrences', 'exact')])

    def healthy_current(self, scan, version):
        self.completed(scan, 'current_graph', 2 if version == 7 else 3)
        self.assertFalse(any(f.check_id == 'current_graph' for f in scan.findings))

    def test_populated_true_versions_complete_exact_selected_graph_without_certification(self):
        for version in range(7, 11):
            with self.subTest(version=version), tempfile.TemporaryDirectory() as td:
                path = Path(td) / 'public.sqlite'
                create_public_graph_database(path, version)
                scan = SQLiteIntegrityScanner().scan(str(path))
                self.completed(scan, 'current_graph', 2 if version == 7 else 3)
                self.completed(scan, 'historical_graph', 4 if version == 7 else 8)
                self.assertFalse(scan.findings)
                self.assertTrue(scan.implemented_scope_complete)
                report = CheckIntegrity(SQLiteIntegrityScanner()).execute(str(path))
                self.assertEqual((report.exit_code, report.complete), (4, False))
                self.assertEqual(report.coverage_revision, 'D2')

    def test_old_full_descriptor_count_mismatch_belongs_to_history(self):
        for version in range(7, 11):
            with self.subTest(version=version), tempfile.TemporaryDirectory() as td:
                path = Path(td) / 'public.sqlite'
                create_public_graph_database(path, version)
                change(path, 'UPDATE graph_builds SET edge_count=2 WHERE id=?', (OLD_BUILD,))
                scan = SQLiteIntegrityScanner().scan(str(path))
                self.findings(scan, 'historical_graph', 'graph_counts_invalid')
                self.healthy_current(scan, version)
                self.completed(scan, 'historical_graph', 4 if version == 7 else 8)

    def test_complementary_current_full_change_is_mirror_not_edge_corruption(self):
        for version in range(7, 11):
            with self.subTest(version=version), tempfile.TemporaryDirectory() as td:
                path = Path(td) / 'public.sqlite'
                create_public_graph_database(path, version)
                change(path, 'UPDATE graph_edges SET score=0.6,distance=0.4')
                scan = SQLiteIntegrityScanner().scan(str(path))
                self.findings(scan, 'current_graph', 'graph_mirror_invalid')
                self.completed(scan, 'historical_graph', 4 if version == 7 else 8)
                self.completed(scan, 'current_graph', 2 if version == 7 else 3)

    def test_current_positioned_mirror_fault_leaves_full_relation_healthy(self):
        for version in range(8, 11):
            with self.subTest(version=version), tempfile.TemporaryDirectory() as td:
                path = Path(td) / 'public.sqlite'
                create_public_graph_database(path, version)
                change(path, 'UPDATE graph_positioned_edges SET score=0.6,distance=0.4')
                scan = SQLiteIntegrityScanner().scan(str(path))
                self.findings(scan, 'current_graph', 'graph_mirror_invalid')
                self.completed(scan, 'current_graph', 3)
                self.completed(scan, 'historical_graph', 8)

    def test_old_position_descriptor_mismatch_leaves_full_and_current_healthy(self):
        for version in range(8, 11):
            with self.subTest(version=version), tempfile.TemporaryDirectory() as td:
                path = Path(td) / 'public.sqlite'
                create_public_graph_database(path, version)
                change(path, 'UPDATE graph_build_positioned_snapshots SET edge_count=2 WHERE build_id=?', (OLD_BUILD,))
                scan = SQLiteIntegrityScanner().scan(str(path))
                self.findings(scan, 'historical_graph', 'graph_counts_invalid')
                self.healthy_current(scan, version)
                self.completed(scan, 'historical_graph', 8)

    def test_old_edge_inverse_and_blank_policy_are_one_ored_occurrence_per_row(self):
        for version in range(7, 11):
            tables = ('graph_build_edges',) if version == 7 else ('graph_build_edges', 'graph_build_positioned_edges')
            for table in tables:
                for fault in ('distance=0.5', "distance_policy_version=''", "distance=0.5,distance_policy_version=''"):
                    with self.subTest(version=version, table=table, fault=fault), tempfile.TemporaryDirectory() as td:
                        path = Path(td) / 'public.sqlite'
                        create_public_graph_database(path, version)
                        change(path, f'UPDATE {table} SET {fault} WHERE build_id=?', (OLD_BUILD,))
                        scan = SQLiteIntegrityScanner().scan(str(path))
                        self.findings(scan, 'historical_graph', 'graph_edge_invalid')
                        self.healthy_current(scan, version)
                        self.completed(scan, 'historical_graph', 4 if version == 7 else 8)

    def test_real_late_error_retains_old_bad_edge_lower_bound_and_attempts_cleanup(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'public.sqlite'
            create_public_graph_database(path)
            change(path, 'UPDATE graph_build_edges SET distance=0.5 WHERE build_id=?', (OLD_BUILD,))
            observed = GraphObservation(late_error=True)
            with patch('sqlite3.connect', observed.connect):
                scan = SQLiteIntegrityScanner().scan(str(path))
            history = check(scan, 'historical_graph')
            self.assertEqual((history.state, history.count_precision), ('interrupted', 'lower_bound'))
            edge = [f for f in scan.findings if f.code == 'graph_edge_invalid']
            self.assertEqual([(f.check_id, f.count, f.count_precision) for f in edge], [('historical_graph', 1, 'lower_bound')])
            self.assertEqual(scan.stop_reason, 'read_error')
            self.assertIn('read_failed', [f.code for f in scan.findings])
            self.assertFalse(scan.implemented_scope_complete)
            self.assertEqual(observed.injected, 1)
            self.assertTrue(all(c.close_attempts for c in observed.cursors))
            self.assertTrue(all(db.closed for db in observed.connections))
            self.assertNotIn('PRIVATE', repr(scan))
            class RetainedScan:
                def scan(self, database, deadline_seconds=120):
                    return scan
            report = CheckIntegrity(RetainedScan()).execute(str(path))
            self.assertEqual((report.exit_code, report.complete), (4, False))

    def test_graph_streaming_all_delivered_rows_charge_budget_and_wal_snapshot_is_pinned(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'public.sqlite'
            create_public_graph_database(path)
            baseline = GraphObservation()
            with patch('sqlite3.connect', baseline.connect):
                healthy = SQLiteIntegrityScanner().scan(str(path))
            with self.subTest(control='streaming'):
                self.completed(healthy, 'historical_graph', 8)
                self.assertGreater(baseline.graph_rows, 8, 'operational rows include mirror/preflight/lookup work')
            capped = GraphObservation()
            with patch('sqlite3.connect', capped.connect), patch(
                    'music_analyzer.infrastructure.persistence.integrity.MAX_ROWS', baseline.delivered - 1):
                scan = SQLiteIntegrityScanner().scan(str(path))
            self.assertEqual(scan.stop_reason, 'row_limit')
            self.assertIn('row_limit_reached', [f.code for f in scan.findings])
            self.assertFalse(scan.implemented_scope_complete)
            self.assertLessEqual(capped.delivered, baseline.delivered)
            with closing(sqlite3.connect(path)) as db:
                self.assertEqual(db.execute('PRAGMA journal_mode=WAL').fetchone(), ('wal',))
            commits = []
            def commit_after_graph_read():
                # Exactly two live connections: scanner snapshot and writer.
                with closing(baseline.real_connect(path, timeout=1)) as writer:
                    writer.execute('UPDATE graph_builds SET edge_count=2 WHERE id=?', (OLD_BUILD,))
                    writer.commit()
                commits.append(True)
            pinned = GraphObservation(barrier=commit_after_graph_read)
            with patch('sqlite3.connect', pinned.connect):
                old = SQLiteIntegrityScanner().scan(str(path))
            self.assertEqual(commits, [True], 'graph-specific WAL barrier must actually fire')
            self.completed(old, 'historical_graph', 8)
            self.assertFalse(old.findings)
            fresh = SQLiteIntegrityScanner().scan(str(path))
            self.findings(fresh, 'historical_graph', 'graph_counts_invalid')
