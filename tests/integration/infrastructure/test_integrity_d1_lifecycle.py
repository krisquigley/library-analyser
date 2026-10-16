"""Fresh independent operational lifecycle packet, no unbounded fixtures."""
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from music_analyzer.infrastructure.persistence.integrity import SQLiteIntegrityScanner
from tests.integration.infrastructure.integrity_d1_public_fixture import create_public_core_database
from tests.integration.infrastructure.test_integrity_d1_safety import ConnectObservation, ObservedConnection

IDS = ('compatibility', 'schema', 'core_rows', 'metadata', 'retained_stages', 'current_graph',
       'historical_graph', 'current_evidence', 'historical_evidence', 'sqlite_physical', 'sqlite_foreign_keys', 'resource_access')


class LifecycleConnection(ObservedConnection):
    def __init__(self, connection, *, late_error=None, cleanup_error=False):
        super().__init__(connection)
        self.late_error = late_error
        self.cleanup_error = cleanup_error
        self.progress_handlers = []
        self.injected = []

    def execute(self, sql, *args):
        if self.late_error is not None and 'SELECT duration_seconds' in sql:
            self.injected.append(self.late_error)
            raise self.late_error('PRIVATE SQL TARGET PAYLOAD')
        return self.connection.execute(sql, *args)

    def set_progress_handler(self, handler, steps):
        self.progress_handlers.append((handler, steps))
        return self.connection.set_progress_handler(handler, steps)

    def close(self):
        super().close()
        if self.cleanup_error:
            raise sqlite3.OperationalError('PRIVATE CLEANUP PATH')


class LifecycleObservation(ConnectObservation):
    def __init__(self, **options):
        super().__init__()
        self.options = options

    def connect(self, database, **kwargs):
        self.calls.append((database, kwargs))
        connection = LifecycleConnection(self.real_connect(database, **kwargs), **self.options)
        self.connections.append(connection)
        return connection


def capture_target_failure(scanner, path):
    try:
        return scanner.scan(str(path))
    except (sqlite3.Error, KeyboardInterrupt):
        return None


class IntegrityD1Lifecycle(unittest.TestCase):
    def test_healthy_scope_completion_after_cleanup_keeps_full_scope_omitted(self):
        for version in range(6, 11):
            with self.subTest(version=version), tempfile.TemporaryDirectory() as td:
                path = Path(td) / 'public.sqlite'
                create_public_core_database(path, version)
                result = SQLiteIntegrityScanner().scan(str(path))
                self.assertTrue(result.implemented_scope_complete, 'completed selected scope needs honest true flag')
                self.assertEqual(tuple(c.check_id for c in result.checks), IDS)
                self.assertEqual(result.stop_reason, 'completed')
                states = {c.check_id: c.state for c in result.checks}
                for check_id in ('compatibility', 'schema', 'core_rows', 'resource_access'):
                    self.assertEqual(states[check_id], 'completed')
                self.assertEqual(states['metadata'], 'completed')
                self.assertEqual(states['current_graph'], 'not_applicable' if version == 6 else 'completed')
                self.assertEqual(states['historical_evidence'], 'not_applicable' if version < 9 else 'completed')

    def test_absolute_deadline_includes_initial_access_and_cleanup(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'public.sqlite'
            create_public_core_database(path, 6)
            result = SQLiteIntegrityScanner().scan(str(path), deadline_seconds=1e-9)
            self.assertEqual(result.stop_reason, 'deadline', 'override must bound initial work')
            self.assertIn('deadline_exceeded', [f.code for f in result.findings])
            self.assertFalse(result.implemented_scope_complete)

    def test_real_progress_handler_and_remaining_busy_timeout_are_installed(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'public.sqlite'
            create_public_core_database(path, 6)
            observation = LifecycleObservation()
            with patch('sqlite3.connect', observation.connect):
                SQLiteIntegrityScanner().scan(str(path), deadline_seconds=1)
            handlers = [handler for db in observation.connections for handler, steps in db.progress_handlers if handler]
            self.assertTrue(handlers, 'real SQLite VM callback must enforce cooperative deadline')
            busy = [sql for db in observation.connections for sql in db.sql if 'busy_timeout' in sql.lower()]
            self.assertTrue(busy)
            self.assertTrue(all(0 <= int(sql.split('=')[1]) <= 1000 for sql in busy))

    def test_cleanup_failure_is_sanitized_and_supersedes_unsupported(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'public.sqlite'
            create_public_core_database(path, 6)
            with closing(sqlite3.connect(path)) as db:
                db.execute('PRAGMA application_id=123')
            observation = LifecycleObservation(cleanup_error=True)
            with patch('sqlite3.connect', observation.connect):
                result = capture_target_failure(SQLiteIntegrityScanner(), path)
            self.assertIsNotNone(result, 'cleanup must not escape raw target error')
            self.assertEqual(result.stop_reason, 'cleanup_error')
            self.assertIn('application_id_mismatch', [f.code for f in result.findings])
            self.assertIn('cleanup_failed', [f.code for f in result.findings])
            self.assertNotIn('PRIVATE', repr(result))
            self.assertFalse(result.implemented_scope_complete)
            self.assertTrue(all(db.closed for db in observation.connections))

    def test_late_read_failure_preserves_prior_corruption_as_lower_bound(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'public.sqlite'
            create_public_core_database(path, 6)
            with closing(sqlite3.connect(path)) as db:
                db.execute('UPDATE tracks SET size=-1')
                db.commit()
            observation = LifecycleObservation(late_error=sqlite3.OperationalError)
            with patch('sqlite3.connect', observation.connect):
                result = SQLiteIntegrityScanner().scan(str(path))
            self.assertEqual(result.stop_reason, 'read_error')
            self.assertIn('track_size_invalid', [f.code for f in result.findings], 'observed corruption cannot disappear on late error')
            core = next(c for c in result.checks if c.check_id == 'core_rows')
            self.assertEqual(core.state, 'interrupted')
            self.assertEqual(core.count, 2)
            self.assertEqual(core.count_precision, 'lower_bound')
            self.assertTrue(all(db.closed for db in observation.connections))
            self.assertNotIn('PRIVATE', repr(result))

    def test_cancellation_wins_cleanup_failure_and_keeps_prior_findings(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'public.sqlite'
            create_public_core_database(path, 6)
            observation = LifecycleObservation(late_error=KeyboardInterrupt, cleanup_error=True)
            with patch('sqlite3.connect', observation.connect):
                result = capture_target_failure(SQLiteIntegrityScanner(), path)
            self.assertIsNotNone(result, 'SIGINT must return sanitized cancellation after cleanup')
            self.assertEqual(result.stop_reason, 'cancelled')
            self.assertIn('cancelled', [f.code for f in result.findings])
            self.assertIn('cleanup_failed', [f.code for f in result.findings])
            self.assertFalse(result.implemented_scope_complete)
            self.assertTrue(all(db.closed for db in observation.connections))


class LifecycleHelperControls(unittest.TestCase):
    def test_real_open_begin_progress_rollback_close_are_intercepted(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'public #?.sqlite'
            create_public_core_database(path, 6)
            observation = LifecycleObservation()
            callbacks = []
            with patch('sqlite3.connect', observation.connect):
                db = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)
                try:
                    db.execute('PRAGMA query_only=ON')
                    db.execute('BEGIN')
                    self.assertEqual(db.execute('PRAGMA user_version').fetchone(), (6,))
                    handler = lambda: callbacks.append(1) or 0
                    db.set_progress_handler(handler, 1)
                    self.assertEqual(db.execute('WITH RECURSIVE n(x) AS (SELECT 1 UNION ALL SELECT x+1 FROM n WHERE x<100) SELECT sum(x) FROM n').fetchone(), (5050,))
                    db.set_progress_handler(None, 0)
                    db.rollback()
                finally:
                    db.close()
            self.assertEqual(len(observation.calls), 1)
            self.assertIsInstance(observation.calls[0][0], str)
            self.assertIs(observation.calls[0][1]['uri'], True)
            self.assertIn('%23%3F', observation.calls[0][0])
            self.assertTrue(callbacks, 'the real SQLite VM must call installed wrapper handler')
            self.assertEqual(db.progress_handlers, [(handler, 1), (None, 0)])
            self.assertIn('BEGIN', db.sql)
            self.assertIn('ROLLBACK', db.sql)
            self.assertTrue(db.closed)
            with self.assertRaises(sqlite3.ProgrammingError):
                db.connection.execute('SELECT 1')

    def test_late_sqlite_error_and_keyboard_interrupt_injections_are_exact(self):
        for exception_type in (sqlite3.OperationalError, KeyboardInterrupt):
            with self.subTest(exception=exception_type.__name__), tempfile.TemporaryDirectory() as td:
                path = Path(td) / 'public.sqlite'
                create_public_core_database(path, 6)
                observation = LifecycleObservation(late_error=exception_type)
                with patch('sqlite3.connect', observation.connect):
                    db = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)
                    try:
                        db.execute('BEGIN')
                        self.assertEqual(db.execute('SELECT 1').fetchone(), (1,))
                        with self.assertRaises(exception_type) as failure:
                            db.execute('SELECT duration_seconds FROM track_audio')
                        self.assertIs(type(failure.exception), exception_type)
                        self.assertEqual(db.injected, [exception_type])
                        self.assertEqual(db.execute('SELECT 2').fetchone(), (2,))
                        db.rollback()
                    finally:
                        db.close()
                self.assertEqual(len(observation.calls), 1)
                self.assertTrue(db.closed)

    def test_cleanup_failure_happens_only_after_real_close(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'public.sqlite'
            create_public_core_database(path, 6)
            observation = LifecycleObservation(cleanup_error=True)
            with patch('sqlite3.connect', observation.connect):
                db = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)
                db.execute('BEGIN')
                self.assertEqual(db.execute('SELECT 1').fetchone(), (1,))
                db.rollback()
                with self.assertRaises(sqlite3.OperationalError) as failure:
                    db.close()
            self.assertIs(type(failure.exception), sqlite3.OperationalError)
            self.assertTrue(db.closed)
            self.assertEqual(len(observation.calls), 1)
            with self.assertRaises(sqlite3.ProgrammingError):
                db.connection.execute('SELECT 1')


class IntegrityD1LateStopRegression(unittest.TestCase):
    def test_cleanup_keeps_earlier_operational_cause(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'public.sqlite'
            create_public_core_database(path, 6)
            observation = LifecycleObservation(late_error=sqlite3.OperationalError, cleanup_error=True)
            with patch('sqlite3.connect', observation.connect):
                result = SQLiteIntegrityScanner().scan(str(path))
            self.assertEqual(result.stop_reason, 'cleanup_error')
            self.assertIn('read_failed', [f.code for f in result.findings], 'cleanup must retain earlier read cause')
            self.assertIn('cleanup_failed', [f.code for f in result.findings])
