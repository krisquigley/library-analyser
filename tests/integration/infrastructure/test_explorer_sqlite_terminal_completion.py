"""Mixed cursor consumption completes raw and request-correlated outward spans."""
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
