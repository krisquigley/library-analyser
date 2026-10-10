"""Real SQLite cursor settings and keyword calls survive outward observation."""
from contextlib import contextmanager
import sqlite3
import unittest

from tools.explorer_http_sqlite_observation import _ObservedConnection, _SQLiteObservation


SQL = 'SELECT path FROM locations WHERE track_id=? AND available=1 ORDER BY path'


class SQLiteCursorParityTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(':memory:')
        self.addCleanup(self.db.close)
        self.db.execute('CREATE TABLE locations(path, track_id, available)')
        self.db.executemany('INSERT INTO locations VALUES (?, ?, 1)',
                            [('public-a', 'id'), ('public-b', 'id')])
        self.records = []

        @contextmanager
        def context(phase):
            record = {'phase': phase, 'status': 'ok'}
            self.records.append(record)
            yield record

        self.observation = _SQLiteObservation(span_context=context)
        self.raw = self.db.execute(SQL, ('id',))
        self.observed = _ObservedConnection(self.db, self.observation).execute(SQL, ('id',))

    def test_writable_arraysize_controls_default_fetchmany_like_real_sqlite(self):
        self.assertEqual(self.observed.arraysize, self.raw.arraysize)
        self.raw.arraysize = self.observed.arraysize = 2
        expected = self.raw.fetchmany()
        self.assertEqual(len(expected), 2)
        self.assertEqual(self.observed.fetchmany(), expected)
        self.assertEqual(self.observed.fetchmany(), self.raw.fetchmany())
        self.assertEqual([span['fetch_method'] for span in self.fetch_spans()],
                         ['fetchmany', 'fetchmany'])
        self.assertTrue(all(span['status'] == 'ok' for span in self.fetch_spans()))

    def test_keyword_fetchmany_size_matches_real_two_row_sqlite(self):
        expected = self.raw.fetchmany(size=2)
        self.assertEqual(len(expected), 2)
        self.assertEqual(self.observed.fetchmany(size=2), expected)
        self.assertEqual(self.observed.fetchmany(size=2), self.raw.fetchmany(size=2))
        self.assertEqual([span['fetch_method'] for span in self.fetch_spans()],
                         ['fetchmany', 'fetchmany'])
        self.assertTrue(all(span['status'] == 'ok' for span in self.fetch_spans()))

    def test_arraysize_validation_remains_sqlite_validation(self):
        for cursor in (self.raw, self.observed):
            with self.subTest(cursor=type(cursor).__name__):
                with self.assertRaises(TypeError):
                    cursor.arraysize = 'private invalid size'
                self.assertEqual(cursor.arraysize, 1)
        self.assertNotIn('private invalid size', repr(self.observation._spans))

    def test_keyword_empty_positive_fetch_certifies_but_nonterminal_does_not(self):
        self.assertEqual(next(self.observed), next(self.raw))
        self.assertEqual(self.observed.fetchmany(size=1), self.raw.fetchmany(size=1))
        self.assertEqual(self.fetch_spans()[0]['status'], 'partial')
        self.assertEqual(self.records[2]['status'], 'partial')
        self.assertEqual(self.observed.fetchmany(size=0), self.raw.fetchmany(size=0))
        self.assertEqual(self.fetch_spans()[0]['status'], 'partial')
        self.assertEqual(self.observed.fetchmany(size=2), self.raw.fetchmany(size=2))
        self.assertTrue(all(span['status'] == 'ok' for span in self.fetch_spans()))
        self.assertTrue(all(record['status'] == 'ok' for record in self.records))

    def test_failed_keyword_fetch_retains_partial_and_failed_status_without_payload(self):
        next(self.observed)
        self.observed.close()
        with self.assertRaises(sqlite3.ProgrammingError):
            self.observed.fetchmany(size=2)
        self.assertEqual([span['status'] for span in self.fetch_spans()],
                         ['partial', 'failed'])
        self.assertEqual([record['status'] for record in self.records[2:]],
                         ['partial', 'failed'])
        self.assertNotIn('public-a', repr(self.observation._spans))
        self.assertNotIn('closed', repr(self.observation._spans))

    def fetch_spans(self):
        return [span for span in self.observation._spans
                if span['phase'] == 'selected_sql_fetch']
