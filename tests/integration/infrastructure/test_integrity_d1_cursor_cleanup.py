"""Fresh narrow cursor-cleanup regression; validated real wrappers first."""
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from music_analyzer.infrastructure.persistence.integrity import SQLiteIntegrityScanner
from tests.integration.infrastructure.integrity_d1_public_fixture import create_public_core_database
from tests.integration.infrastructure.test_integrity_d1_safety import ConnectObservation, ObservedConnection


class CleanupCursor:
    def __init__(self, cursor, observation, *, fail_close=False, interrupt=False):
        self.cursor = cursor
        self.observation = observation
        self.fail_close = fail_close
        self.interrupt = interrupt
        self.fetch_calls = 0
        self.close_calls = 0
        self.closed = False

    def fetchone(self):
        self.fetch_calls += 1
        if self.interrupt and self.fetch_calls == 2:
            self.observation.interrupts += 1
            raise KeyboardInterrupt('PRIVATE INTERRUPT')
        row = self.cursor.fetchone()
        if row is not None:
            self.observation.delivered += 1
        return row

    def close(self):
        self.close_calls += 1
        self.cursor.close()
        self.closed = True
        if self.fail_close:
            self.observation.close_failures += 1
            raise sqlite3.OperationalError('PRIVATE CURSOR PATH')


class CleanupConnection(ObservedConnection):
    def __init__(self, connection, observation):
        super().__init__(connection)
        self.observation = observation

    def execute(self, sql, *args):
        tracked = 'FROM tracks ORDER BY rowid' in sql
        preflight = tracked and sql.startswith('SELECT CASE')
        if preflight:
            self.observation.core_start = self.observation.delivered
        cursor = CleanupCursor(self.connection.execute(sql, *args), self.observation,
                               fail_close=preflight and self.observation.fail_close,
                               interrupt=tracked and not preflight and self.observation.interrupt)
        if tracked:
            self.observation.paired.append(cursor)
        return cursor


class CursorCleanupObservation(ConnectObservation):
    def __init__(self, *, fail_close=True, interrupt=False):
        super().__init__()
        self.fail_close = fail_close
        self.interrupt = interrupt
        self.delivered = 0
        self.core_start = None
        self.paired = []
        self.close_failures = 0
        self.interrupts = 0

    def connect(self, database, **kwargs):
        self.calls.append((database, kwargs))
        db = CleanupConnection(self.real_connect(database, **kwargs), self)
        self.connections.append(db)
        return db


class CursorCleanupHelperControls(unittest.TestCase):
    def test_real_pair_close_injection_and_second_value_interrupt_are_intercepted(self):
        for interrupt in (False, True):
            with self.subTest(interrupt=interrupt), tempfile.TemporaryDirectory() as td:
                path = Path(td) / 'public.sqlite'
                create_public_core_database(path, 6)
                observation = CursorCleanupObservation(interrupt=interrupt)
                with patch('sqlite3.connect', observation.connect):
                    with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)) as db:
                        db.execute('BEGIN').close()
                        preflight = db.execute("SELECT CASE typeof(id) WHEN 'text' THEN length(CAST(id AS BLOB)) ELSE NULL END FROM tracks ORDER BY rowid")
                        values = db.execute('SELECT id,sha256,size FROM tracks ORDER BY rowid')
                        self.assertEqual(preflight.fetchone(), (71,))
                        self.assertEqual(values.fetchone()[1], '1' * 64)
                        self.assertEqual(preflight.fetchone(), (71,))
                        if interrupt:
                            with self.assertRaises(KeyboardInterrupt) as failure:
                                values.fetchone()
                            self.assertIs(type(failure.exception), KeyboardInterrupt)
                        else:
                            self.assertEqual(values.fetchone()[1], '2' * 64)
                        with self.assertRaises(sqlite3.OperationalError) as failure:
                            preflight.close()
                        self.assertIs(type(failure.exception), sqlite3.OperationalError)
                        values.close()
                self.assertEqual(len(observation.calls), 1)
                self.assertIs(observation.calls[0][1]['uri'], True)
                self.assertEqual(observation.close_failures, 1)
                self.assertEqual(observation.interrupts, int(interrupt))
                self.assertEqual([cursor.close_calls for cursor in observation.paired], [1, 1])
                self.assertTrue(all(cursor.closed for cursor in observation.paired))
                self.assertTrue(db.closed)
                for cursor in observation.paired:
                    with self.assertRaises(sqlite3.ProgrammingError):
                        cursor.cursor.fetchone()


class IntegrityD1CursorCleanup(unittest.TestCase):
    def test_cursor_close_failure_is_cleanup_not_read_error(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'public.sqlite'
            create_public_core_database(path, 6)
            observation = CursorCleanupObservation()
            with patch('sqlite3.connect', observation.connect):
                result = SQLiteIntegrityScanner().scan(str(path))
            self.assertEqual(result.stop_reason, 'cleanup_error', 'cursor cleanup is resource cleanup, not SQL read failure')
            self.assertIn('cleanup_failed', [f.code for f in result.findings])
            self.assertFalse(result.implemented_scope_complete)
            self.assertNotIn('PRIVATE', repr(result))

    def test_failure_closing_preflight_does_not_skip_value_cursor_close(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'public.sqlite'
            create_public_core_database(path, 6)
            observation = CursorCleanupObservation()
            with patch('sqlite3.connect', observation.connect):
                SQLiteIntegrityScanner().scan(str(path))
            self.assertEqual(len(observation.paired), 2)
            self.assertEqual([cursor.close_calls for cursor in observation.paired], [1, 1],
                             'all paired cursors must receive cleanup attempt')
            self.assertTrue(all(db.closed for db in observation.connections))

    def test_cursor_close_failure_preserves_cancellation_cause(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'public.sqlite'
            create_public_core_database(path, 6)
            observation = CursorCleanupObservation(interrupt=True)
            with patch('sqlite3.connect', observation.connect):
                result = SQLiteIntegrityScanner().scan(str(path))
            self.assertEqual(observation.interrupts, 1)
            self.assertEqual(result.stop_reason, 'cancelled', 'cursor failure must not replace KeyboardInterrupt')
            self.assertIn('cleanup_failed', [f.code for f in result.findings])
            self.assertIn('cancelled', [f.code for f in result.findings])

    def test_cursor_close_failure_preserves_row_budget_cause(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'public.sqlite'
            create_public_core_database(path, 6)
            baseline = CursorCleanupObservation(fail_close=False)
            with patch('sqlite3.connect', baseline.connect):
                self.assertTrue(SQLiteIntegrityScanner().scan(str(path)).implemented_scope_complete)
            observation = CursorCleanupObservation()
            with patch('sqlite3.connect', observation.connect), patch(
                    'music_analyzer.infrastructure.persistence.integrity.MAX_ROWS', baseline.core_start + 3):
                result = SQLiteIntegrityScanner().scan(str(path))
            self.assertEqual(result.stop_reason, 'cleanup_error')
            self.assertIn('row_limit_reached', [f.code for f in result.findings], 'cursor cleanup must retain prior work stop')
            self.assertIn('cleanup_failed', [f.code for f in result.findings])
