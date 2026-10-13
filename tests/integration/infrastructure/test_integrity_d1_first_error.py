"""Genuine early UTF-8 SQLite fetch errors must precede slow cursor cleanup."""
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
from time import monotonic, sleep
import unittest
from unittest.mock import patch

from music_analyzer.application.use_cases.check_integrity import CheckIntegrity
from music_analyzer.infrastructure.persistence.integrity import SQLiteIntegrityScanner
from tests.integration.infrastructure.integrity_d1_public_fixture import create_public_core_database


CORE_SQL = 'SELECT id,sha256,size FROM tracks ORDER BY rowid'


def malformed_public_database(path):
    create_public_core_database(path, 6)
    with closing(sqlite3.connect(path)) as db:
        db.execute("UPDATE tracks SET sha256=CAST(x'80' AS TEXT) WHERE rowid=1")
        db.commit()


class ErrorObservation:
    def __init__(self, *, slow_close=False, fail_close=False, cancel_close=False,
                 late_fetch=False, slow_connection=False):
        self.real_connect = sqlite3.connect
        self.slow_close = slow_close
        self.fail_close = fail_close
        self.cancel_close = cancel_close
        self.late_fetch = late_fetch
        self.slow_connection = slow_connection
        self.connection_closed_at = None
        self.error_at = None
        self.error_type = None
        self.deadline = None
        self.closed_at = None
        self.connections = []
        self.paired = []

    def connect(self, *args, **kwargs):
        connection = ErrorConnection(self.real_connect(*args, **kwargs), self)
        self.connections.append(connection)
        return connection


class ErrorCursor:
    def __init__(self, cursor, observation, *, preflight):
        self.cursor = cursor
        self.observation = observation
        self.preflight = preflight
        self.close_calls = 0

    def fetchone(self):
        if not self.preflight and self.observation.late_fetch:
            sleep(max(0, self.observation.deadline + .03 - monotonic()))
        try:
            return self.cursor.fetchone()
        except sqlite3.Error as error:
            self.observation.error_at = monotonic()
            self.observation.error_type = type(error)
            raise

    def close(self):
        self.close_calls += 1
        self.cursor.close()
        observation = self.observation
        if self.preflight and observation.error_at is not None:
            if observation.slow_close:
                sleep(max(0, observation.deadline + .03 - monotonic()))
            observation.closed_at = monotonic()
            if observation.cancel_close:
                raise KeyboardInterrupt('PUBLIC cleanup cancellation')
            if observation.fail_close:
                raise sqlite3.OperationalError('PUBLIC cleanup failure')


class ErrorConnection:
    def __init__(self, connection, observation):
        self.connection = connection
        self.observation = observation
        self.closed = False

    def set_progress_handler(self, callback, steps):
        if callback is not None:
            self.observation.deadline = callback.__self__.deadline
        return self.connection.set_progress_handler(callback, steps)

    def execute(self, sql, *args):
        cursor = self.connection.execute(sql, *args)
        if 'FROM tracks ORDER BY rowid' in sql:
            cursor = ErrorCursor(cursor, self.observation,
                                 preflight=sql != CORE_SQL)
            self.observation.paired.append(cursor)
        return cursor

    def close(self):
        if self.observation.slow_connection and self.observation.error_at is not None:
            sleep(max(0, self.observation.deadline + .03 - monotonic()))
        self.connection.close()
        self.closed = True
        self.observation.connection_closed_at = monotonic()


class FirstErrorHelperControls(unittest.TestCase):
    def test_real_fetch_error_and_slow_connection_cleanup_are_intercepted(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'public.sqlite'
            malformed_public_database(path)
            observation = ErrorObservation(slow_connection=True)
            observation.deadline = monotonic() + .15
            with patch('sqlite3.connect', observation.connect):
                with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)) as db:
                    values = db.execute(CORE_SQL)
                    with self.assertRaises(sqlite3.OperationalError):
                        values.fetchone()
                    self.assertLess(observation.error_at, observation.deadline)
                    values.close()
            self.assertGreater(observation.connection_closed_at, observation.deadline)
            self.assertTrue(db.closed)
            with self.assertRaises(sqlite3.ProgrammingError):
                db.connection.execute('SELECT 1')

    def test_real_fetchone_error_and_slow_pair_cleanup_are_intercepted(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'public.sqlite'
            malformed_public_database(path)
            observation = ErrorObservation(slow_close=True)
            observation.deadline = monotonic() + .15
            with patch('sqlite3.connect', observation.connect):
                with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)) as db:
                    preflight = db.execute('SELECT length(CAST(sha256 AS BLOB)) FROM tracks ORDER BY rowid')
                    self.assertEqual(preflight.fetchone(), (1,))
                    values = db.execute(CORE_SQL)
                    with self.assertRaises(sqlite3.OperationalError):
                        values.fetchone()
                    self.assertIs(observation.error_type, sqlite3.OperationalError)
                    self.assertLess(observation.error_at, observation.deadline)
                    preflight.close()
                    values.close()
            self.assertGreater(observation.closed_at, observation.deadline)
            self.assertEqual([cursor.close_calls for cursor in observation.paired], [1, 1])
            self.assertTrue(all(connection.closed for connection in observation.connections))
            for cursor in observation.paired:
                with self.assertRaises(sqlite3.ProgrammingError):
                    cursor.cursor.fetchone()


class IntegrityD1FirstError(unittest.TestCase):
    def scan(self, **controls):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'public.sqlite'
            malformed_public_database(path)
            observation = ErrorObservation(**controls)
            with patch('sqlite3.connect', observation.connect):
                result = CheckIntegrity(SQLiteIntegrityScanner()).execute(str(path), deadline_seconds=.5)
            self.assertIs(observation.error_type, sqlite3.OperationalError)
            if observation.late_fetch:
                self.assertGreater(observation.error_at, observation.deadline)
            else:
                self.assertLess(observation.error_at, observation.deadline)
            self.assertEqual([cursor.close_calls for cursor in observation.paired], [1, 1])
            self.assertTrue(all(connection.closed for connection in observation.connections))
            return result, observation

    def test_early_utf8_fetch_error_remains_read_error_when_cursor_cleanup_expires(self):
        result, observation = self.scan(slow_close=True)
        self.assertGreater(observation.closed_at, observation.deadline)
        self.assertEqual((result.stop_reason, result.status, result.exit_code),
                         ('read_error', 'incomplete', 4))
        self.assertIn('read_failed', [item.code for item in result.findings])
        self.assertNotIn('deadline_exceeded', [item.code for item in result.findings])

    def test_early_utf8_fetch_error_remains_read_error_when_connection_cleanup_expires(self):
        result, observation = self.scan(slow_connection=True)
        self.assertGreater(observation.connection_closed_at, observation.deadline)
        self.assertEqual((result.stop_reason, result.status, result.exit_code),
                         ('read_error', 'incomplete', 4))
        self.assertIn('read_failed', [item.code for item in result.findings])
        self.assertNotIn('deadline_exceeded', [item.code for item in result.findings])

    def test_utf8_fetch_error_returning_after_deadline_remains_deadline(self):
        result, _ = self.scan(late_fetch=True)
        self.assertEqual((result.stop_reason, result.exit_code), ('deadline', 4))
        self.assertIn('deadline_exceeded', [item.code for item in result.findings])
        self.assertNotIn('read_failed', [item.code for item in result.findings])

    def test_early_utf8_error_without_cleanup_delay_is_read_error(self):
        result, _ = self.scan()
        self.assertEqual(result.stop_reason, 'read_error')
        self.assertIn('read_failed', [item.code for item in result.findings])

    def test_cleanup_failure_overrides_but_retains_first_read_finding(self):
        result, _ = self.scan(slow_close=True, fail_close=True)
        self.assertEqual((result.stop_reason, result.exit_code), ('cleanup_error', 4))
        self.assertEqual({item.code for item in result.findings}, {'read_failed', 'cleanup_failed'})

    def test_cleanup_cancellation_overrides_but_retains_first_read_finding(self):
        result, _ = self.scan(slow_close=True, cancel_close=True)
        self.assertEqual((result.stop_reason, result.exit_code), ('cancelled', 130))
        self.assertEqual({item.code for item in result.findings}, {'read_failed', 'cancelled'})
