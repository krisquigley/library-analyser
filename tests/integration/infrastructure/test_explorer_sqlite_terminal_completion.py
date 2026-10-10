"""Mixed cursor consumption completes raw and request-correlated outward spans."""
from contextlib import contextmanager
from pathlib import Path
import sqlite3
import unittest

from music_explorer.infrastructure.explorer_readonly import ReadOnlyExplorerSQLiteRepository
from tools.explorer_fixture_inspection import fingerprint_sqlite_files
from tools.explorer_http_server_observation import ServerObservation
from tools.explorer_http_sqlite_observation import observe_sqlite
from tools.explorer_synthetic_fixture import public_synthetic_fixture


SQL = 'SELECT path FROM locations WHERE track_id=? AND available=1 ORDER BY path'


class SQLiteTerminalCompletionTests(unittest.TestCase):
    def exercise(self, terminal, expected_status, failed=False):
        original = ReadOnlyExplorerSQLiteRepository._connection
        server = ServerObservation()
        context = {'request_id': 'mixed-cursor', 'stack': [], 'spans': []}
        server.local.context = context
        with public_synthetic_fixture() as fixture:
            path = Path(fixture['db_path'])
            before = fingerprint_sqlite_files(path)
            repository = ReadOnlyExplorerSQLiteRepository(str(path))
            with observe_sqlite(span_context=server.span) as observation:
                with repository._connection() as db:
                    handle = db.execute('SELECT track_id FROM locations WHERE available=1 '
                                        'ORDER BY track_id LIMIT 1').fetchone()[0]
                    cursor = db.execute(SQL, (handle,))
                    payload = next(cursor)[0]
                    if failed:
                        with self.assertRaises(sqlite3.ProgrammingError):
                            terminal(cursor)
                    else:
                        terminal(cursor)
                    raw = [span for span in observation._spans
                           if span.get('fetch_method') == 'iteration']
                    correlated = [span for span in context['spans']
                                  if span['phase'] == 'selected_sql_fetch']
                    self.assertEqual(len(raw), 1)
                    self.assertEqual(raw[0]['status'], expected_status)
                    self.assertEqual(correlated[0]['status'], expected_status)
                    if failed:
                        self.assertEqual(observation._spans[-1]['status'], 'failed')
                        self.assertEqual(correlated[-1]['status'], 'failed')
            self.assertIs(ReadOnlyExplorerSQLiteRepository._connection, original)
            report = observation.report(path)
            self.assertEqual(before, fingerprint_sqlite_files(path))
            self.assertNotIn(payload, repr(report))
            self.assertEqual(context['stack'], [])
        del server.local.context

    def exercise_callback_failure(self, method, args, *, entry_failure=False):
        original = ReadOnlyExplorerSQLiteRepository._connection
        records = []
        fetch_count = 0
        private_error = 'private callback error must not be published'

        @contextmanager
        def callback(phase):
            nonlocal fetch_count
            if phase == 'selected_sql_fetch':
                fetch_count += 1
            failing = phase == 'selected_sql_fetch' and fetch_count == 2
            if failing and entry_failure:
                raise RuntimeError(private_error)
            record = {'phase': phase, 'status': 'ok'}
            records.append(record)
            yield record
            if failing:
                raise RuntimeError(private_error)

        with public_synthetic_fixture() as fixture:
            path = Path(fixture['db_path'])
            before = fingerprint_sqlite_files(path)
            repository = ReadOnlyExplorerSQLiteRepository(str(path))
            with observe_sqlite(span_context=callback) as observation:
                with repository._connection() as db:
                    handle = db.execute('SELECT track_id FROM locations WHERE available=1 '
                                        'ORDER BY track_id LIMIT 1').fetchone()[0]
                    cursor = db.execute(SQL, (handle,))
                    payload = next(cursor)[0]
                    with self.assertRaisesRegex(RuntimeError, private_error):
                        getattr(cursor, method)(*args)
                    raw = [span for span in observation._spans
                           if span['phase'] == 'selected_sql_fetch']
                    correlated = [record for record in records
                                  if record['phase'] == 'selected_sql_fetch']
                    self.assertEqual([span['status'] for span in raw], ['partial', 'failed'])
                    self.assertEqual([record['status'] for record in correlated],
                                     ['partial'] if entry_failure else ['partial', 'failed'])
            self.assertIs(ReadOnlyExplorerSQLiteRepository._connection, original)
            report = observation.report(path)
            self.assertEqual(before, fingerprint_sqlite_files(path))
            self.assertNotIn(payload, repr(report))
            self.assertNotIn(private_error, repr(report))
            self.assertNotIn(private_error, repr(records))

    def test_callback_exit_failure_marks_raw_and_correlated_terminal_fetch_failed(self):
        for method, args in (('fetchall', ()), ('fetchone', ()), ('fetchmany', (1,))):
            with self.subTest(method=method):
                self.exercise_callback_failure(method, args)

    def test_callback_entry_failure_does_not_invent_correlated_record(self):
        self.exercise_callback_failure('fetchall', (), entry_failure=True)

    def test_successful_terminal_fetch_completes_previous_iteration(self):
        def fetchall(cursor):
            self.assertEqual(cursor.fetchall(), [])

        def fetchone(cursor):
            self.assertIsNone(cursor.fetchone())

        def fetchmany(cursor):
            self.assertEqual(cursor.fetchmany(1), [])

        def default_fetchmany(cursor):
            self.assertEqual(cursor.fetchmany(), [])

        for terminal in (fetchall, fetchone, fetchmany, default_fetchmany):
            with self.subTest(method=terminal.__name__):
                self.exercise(terminal, 'ok')

    def test_zero_size_fetch_and_close_do_not_certify_iteration(self):
        def zero(cursor):
            self.assertEqual(cursor.fetchmany(0), [])

        for terminal in (zero, lambda cursor: cursor.close()):
            with self.subTest(method=terminal):
                self.exercise(terminal, 'partial')

    def test_failed_terminal_fetch_preserves_partial_iteration(self):
        for method, args in (('fetchall', ()), ('fetchone', ()), ('fetchmany', (1,))):
            with self.subTest(method=method):
                def closed_fetch(cursor):
                    cursor.close()
                    getattr(cursor, method)(*args)

                self.exercise(closed_fetch, 'partial', failed=True)
