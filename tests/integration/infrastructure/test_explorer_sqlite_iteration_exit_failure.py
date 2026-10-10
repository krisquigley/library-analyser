"""Real SQLite iteration must not certify a failed outward context exit."""
from contextlib import closing, contextmanager
from pathlib import Path
import sqlite3
import unittest
from unittest.mock import patch

from music_explorer.infrastructure.explorer_readonly import ReadOnlyExplorerSQLiteRepository
from tools.explorer_fixture_inspection import fingerprint_sqlite_files
from tools.explorer_http_server_observation import ServerObservation
from tools.explorer_http_sqlite_observation import observe_sqlite
from tools.explorer_synthetic_fixture import public_synthetic_fixture


SQL = 'SELECT path FROM locations WHERE track_id=? AND available=1 ORDER BY path'


class SQLiteIterationExitFailureTests(unittest.TestCase):
    def exercise_exit_failure(self, *, failing_fetch, terminal_method, expected_statuses):
        original = ReadOnlyExplorerSQLiteRepository._connection
        server = ServerObservation()
        context = {'request_id': 'iteration-exit-failure', 'stack': [], 'spans': []}
        server.local.context = context
        fetch_count = 0
        private_error = 'private iteration callback exit error'

        @contextmanager
        def callback(phase):
            nonlocal fetch_count
            if phase == 'selected_sql_fetch':
                fetch_count += 1
            failing = phase == 'selected_sql_fetch' and fetch_count == failing_fetch
            with server.span(phase) as record:
                try:
                    yield record
                finally:
                    # Also fail when exhaustion throws StopIteration through yield.
                    if failing:
                        raise RuntimeError(private_error)

        try:
            with public_synthetic_fixture() as fixture:
                path = Path(fixture['db_path'])
                before = fingerprint_sqlite_files(path)
                repository = ReadOnlyExplorerSQLiteRepository(str(path))
                with observe_sqlite(span_context=callback) as observation:
                    with repository._connection() as db:
                        handle = db.execute(
                            'SELECT track_id FROM locations WHERE available=1 '
                            'ORDER BY track_id LIMIT 1').fetchone()[0]
                        self.assertEqual(db.execute(
                            'SELECT count(*) FROM locations WHERE track_id=? AND available=1',
                            (handle,)).fetchone()[0], 1)
                        payload = db.execute(SQL + ' LIMIT 1', (handle,)).fetchone()[0]
                        raw_start = len(observation._spans)
                        correlated_start = len(context['spans'])
                        cursor = db.execute(SQL, (handle,))
                        if failing_fetch == 1:
                            with self.assertRaisesRegex(RuntimeError, private_error):
                                next(cursor)
                            self.assertEqual(cursor.fetchall(), [])
                        else:
                            self.assertEqual(next(cursor)[0], payload)
                            with self.assertRaisesRegex(RuntimeError, private_error):
                                next(cursor)
                        raw = [span for span in observation._spans[raw_start:]
                               if span['phase'] == 'selected_sql_fetch']
                        correlated = [span for span in context['spans'][correlated_start:]
                                      if span['phase'] == 'selected_sql_fetch']
                        self.assertEqual([span['fetch_method'] for span in raw],
                                         ['iteration', terminal_method])
                self.assertIs(ReadOnlyExplorerSQLiteRepository._connection, original)
                report = observation.report(path)
                self.assertEqual(before, fingerprint_sqlite_files(path))
                self.assertEqual(context['stack'], [])
                self.assertNotIn(payload, repr(report))
                self.assertNotIn(private_error, repr(report))
                self.assertNotIn(private_error, repr(context['spans']))
                for channel, records in (('RAW', raw), ('correlated', correlated)):
                    with self.subTest(channel=channel):
                        self.assertEqual([span['status'] for span in records], expected_statuses)
        finally:
            del server.local.context

    def test_failed_first_next_keeps_failed_status_when_fetchall_returns_remaining_row(self):
        records = []
        fetch_count = 0
        private_error = 'private two-row exit error'

        @contextmanager
        def callback(phase):
            nonlocal fetch_count
            if phase == 'selected_sql_fetch':
                fetch_count += 1
            failing = phase == 'selected_sql_fetch' and fetch_count == 1
            record = {'phase': phase, 'status': 'ok'}
            records.append(record)
            yield record
            if failing:
                raise RuntimeError(private_error)

        original = ReadOnlyExplorerSQLiteRepository._connection
        with public_synthetic_fixture() as fixture, closing(sqlite3.connect(':memory:')) as real_db:
            real_db.execute('CREATE TABLE locations (track_id TEXT, available INTEGER, path TEXT)')
            real_db.executemany('INSERT INTO locations VALUES (?, ?, ?)',
                                [('track', 1, '/public/first'), ('track', 1, '/public/second')])
            real_db.commit()
            before = list(real_db.iterdump())

            @contextmanager
            def connection(repository):
                yield real_db

            repository = ReadOnlyExplorerSQLiteRepository(str(fixture['db_path']))
            with patch.object(ReadOnlyExplorerSQLiteRepository, '_connection', connection):
                with observe_sqlite(span_context=callback) as observation:
                    with repository._connection() as db:
                        cursor = db.execute(SQL, ('track',))
                        with self.assertRaisesRegex(RuntimeError, private_error):
                            next(cursor)
                        self.assertEqual(cursor.fetchall(), [('/public/second',)])
                self.assertIs(ReadOnlyExplorerSQLiteRepository._connection, connection)
            self.assertIs(ReadOnlyExplorerSQLiteRepository._connection, original)
            self.assertEqual(list(real_db.iterdump()), before)
            raw = [span for span in observation._spans if span['phase'] == 'selected_sql_fetch']
            correlated = [record for record in records if record['phase'] == 'selected_sql_fetch']
            self.assertNotIn(private_error, repr(observation._spans))
            self.assertNotIn(private_error, repr(records))
            for channel, spans in (('RAW', raw), ('correlated', correlated)):
                with self.subTest(channel=channel):
                    self.assertEqual([span['status'] for span in spans], ['failed', 'ok'])

    def test_failed_first_next_is_not_promoted_by_successful_fetchall(self):
        self.exercise_exit_failure(failing_fetch=1, terminal_method='fetchall',
                                   expected_statuses=['failed', 'ok'])

    def test_failed_exhaustion_next_does_not_complete_previous_iteration(self):
        self.exercise_exit_failure(failing_fetch=2, terminal_method='iteration',
                                   expected_statuses=['partial', 'failed'])
