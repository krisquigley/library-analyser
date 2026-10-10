"""SQLite index-sized fetches preserve results and terminal observation semantics."""
from contextlib import closing
from pathlib import Path
import sqlite3
import unittest

from music_explorer.infrastructure.explorer_readonly import ReadOnlyExplorerSQLiteRepository
from tools.explorer_fixture_inspection import fingerprint_sqlite_files
from tools.explorer_http_server_observation import ServerObservation
from tools.explorer_http_sqlite_observation import observe_sqlite
from tools.explorer_synthetic_fixture import public_synthetic_fixture


SQL = 'SELECT path FROM locations WHERE track_id=? AND available=1 ORDER BY path'


class IndexSize:
    def __init__(self, value):
        self.value = value
        self.calls = 0

    def __index__(self):
        self.calls += 1
        if self.calls > 1:
            raise AssertionError('size converted more than once')
        return self.value


class InvalidIndex:
    def __index__(self):
        return 'not an integer'


class FailingIndex:
    def __index__(self):
        raise ValueError('size conversion failed')


class SQLiteFetchmanyIndexTests(unittest.TestCase):
    def test_index_size_matches_sqlite_and_certifies_only_positive_terminal_fetch(self):
        for correlated in (False, True):
            for keyword in (False, True):
                for value in (1, 2, 0, -1):
                    with self.subTest(correlated=correlated, keyword=keyword, value=value):
                        self.exercise(value, keyword, correlated)

    def exercise(self, value, keyword, correlated):
        original = ReadOnlyExplorerSQLiteRepository._connection
        server = ServerObservation()
        context = {'request_id': 'index-size', 'stack': [], 'spans': []}
        server.local.context = context
        with public_synthetic_fixture() as fixture:
            path = Path(fixture['db_path'])
            before = fingerprint_sqlite_files(path)
            repository = ReadOnlyExplorerSQLiteRepository(str(path))
            with closing(sqlite3.connect(path)) as baseline:
                handle = baseline.execute('SELECT track_id FROM locations WHERE available=1 '
                                          'ORDER BY track_id LIMIT 1').fetchone()[0]
                native = baseline.execute(SQL, (handle,))
                native_size = IndexSize(value)
                native_error = None
                try:
                    expected = (native.fetchmany(size=native_size) if keyword
                                else native.fetchmany(native_size))
                except ValueError as error:
                    # Python 3.14 rejects negative sizes; earlier versions drain.
                    native_error = str(error)
                self.assertEqual(native_size.calls, 1)
            with observe_sqlite(span_context=server.span if correlated else None) as observation:
                with repository._connection() as db:
                    cursor = db.execute(SQL, (handle,))
                    size = IndexSize(value)
                    def fetch(cursor, size):
                        if native_error is not None:
                            with self.assertRaises(ValueError) as raised:
                                cursor.fetchmany(size=size) if keyword else cursor.fetchmany(size)
                            self.assertEqual(str(raised.exception), native_error)
                            return None
                        return cursor.fetchmany(size=size) if keyword else cursor.fetchmany(size)

                    rows = fetch(cursor, size)
                    self.assertEqual(rows, None if native_error is not None else expected)
                    self.assertEqual(size.calls, 1)
                    # A fresh cursor leaves one iteration span awaiting certification.
                    cursor = db.execute(SQL, (handle,))
                    payload = next(cursor)[0]
                    terminal_size = IndexSize(value)
                    self.assertEqual(fetch(cursor, terminal_size),
                                     None if native_error is not None else [])
                    self.assertEqual(terminal_size.calls, 1)
                    raw = [span for span in observation._spans
                           if span.get('fetch_method') == 'iteration']
                    expected_status = 'ok' if value > 0 else 'partial'
                    self.assertEqual([span['status'] for span in raw], [expected_status])
                    if correlated:
                        fetches = [span for span in context['spans']
                                   if span['phase'] == 'selected_sql_fetch']
                        self.assertEqual(fetches[1]['status'], expected_status)
                    self.assertEqual(observation._spans[-1]['status'],
                                     'failed' if native_error is not None else 'ok')
            self.assertIs(ReadOnlyExplorerSQLiteRepository._connection, original)
            self.assertEqual(before, fingerprint_sqlite_files(path))
            self.assertNotIn(payload, repr(observation.report(path)))
            self.assertEqual(context['stack'], [])
        del server.local.context

    def test_invalid_sizes_and_arguments_preserve_sqlite_errors(self):
        cases = [((None,), {}), (('2',), {}), ((1.5,), {}), ((2 ** 100,), {}),
                 ((InvalidIndex(),), {}), ((FailingIndex(),), {}),
                 ((1, 2), {}), ((1,), {'size': 1}), ((), {'unknown': 1})]
        with public_synthetic_fixture() as fixture:
            repository = ReadOnlyExplorerSQLiteRepository(fixture['db_path'])
            for closed in (False, True):
                for args, kwargs in cases:
                    with self.subTest(args=args, kwargs=kwargs, closed=closed):
                        with closing(sqlite3.connect(fixture['db_path'])) as native:
                            cursor = native.execute('SELECT 1')
                            if closed:
                                cursor.close()
                            try:
                                cursor.fetchmany(*args, **kwargs)
                            except Exception as error:
                                expected_type, expected_message = type(error), str(error)
                            else:
                                self.fail('invalid input unexpectedly accepted')
                        with observe_sqlite() as observation:
                            with repository._connection() as db:
                                handle = db.execute('SELECT track_id FROM locations LIMIT 1').fetchone()[0]
                                cursor = db.execute(SQL, (handle,))
                                next(cursor)
                                if closed:
                                    cursor.close()
                                with self.assertRaises(expected_type) as raised:
                                    cursor.fetchmany(*args, **kwargs)
                                self.assertEqual(str(raised.exception), expected_message)
                                fetches = [span for span in observation._spans
                                           if span['phase'] == 'selected_sql_fetch']
                                self.assertEqual([span['status'] for span in fetches],
                                                 ['partial', 'failed'])

    def test_closed_cursor_preserves_sqlite_error_and_single_index_conversion(self):
        with public_synthetic_fixture() as fixture:
            repository = ReadOnlyExplorerSQLiteRepository(fixture['db_path'])
            with closing(sqlite3.connect(fixture['db_path'])) as native:
                cursor = native.execute('SELECT 1')
                cursor.close()
                native_size = IndexSize(1)
                with self.assertRaises(sqlite3.ProgrammingError) as expected:
                    cursor.fetchmany(native_size)
                self.assertEqual(native_size.calls, 1)
            with observe_sqlite() as observation:
                with repository._connection() as db:
                    handle = db.execute('SELECT track_id FROM locations LIMIT 1').fetchone()[0]
                    cursor = db.execute(SQL, (handle,))
                    next(cursor)
                    cursor.close()
                    size = IndexSize(1)
                    with self.assertRaises(sqlite3.ProgrammingError) as raised:
                        cursor.fetchmany(size)
                    self.assertEqual(str(raised.exception), str(expected.exception))
                    self.assertEqual(size.calls, 1)
                    fetches = [span for span in observation._spans
                               if span['phase'] == 'selected_sql_fetch']
                    self.assertEqual([span['status'] for span in fetches], ['partial', 'failed'])
