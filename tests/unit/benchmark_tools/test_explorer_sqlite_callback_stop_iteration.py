"""Optional observer callbacks must not disguise failures as cursor exhaustion."""
from contextlib import closing
import sqlite3
import unittest

from tools.explorer_http_server_observation import ServerObservation
from tools.explorer_http_sqlite_observation import _ObservedConnection, _SQLiteObservation


SQL = 'SELECT path FROM locations WHERE track_id=? AND available=1 ORDER BY path'


class SQLiteCallbackStopIterationTests(unittest.TestCase):
    def exercise_callback_failure(self, stage, failing_fetch, method='iteration'):
        server = ServerObservation()
        context = {'request_id': 'public-callback-regression', 'stack': [], 'spans': []}
        server.local.context = context
        self.addCleanup(delattr, server.local, 'context')
        fetch_count = 0
        private_error = 'private callback StopIteration detail'

        class CallbackContext:
            def __init__(self, phase, failing):
                self.phase = phase
                self.failing = failing

            def __enter__(self):
                if self.failing and stage == 'entry':
                    raise StopIteration(private_error)
                self.manager = server.span(self.phase)
                return self.manager.__enter__()

            def __exit__(self, *exc):
                result = self.manager.__exit__(*exc)
                if self.failing and stage == 'exit':
                    raise StopIteration(private_error)
                return result

        def callback(phase):
            nonlocal fetch_count
            if phase == 'selected_sql_fetch':
                fetch_count += 1
            failing = phase == 'selected_sql_fetch' and fetch_count == failing_fetch
            if failing and stage == 'factory':
                raise StopIteration(private_error)
            return CallbackContext(phase, failing)

        with closing(sqlite3.connect(':memory:')) as db:
            db.execute('CREATE TABLE locations(path, track_id, available)')
            db.executemany('INSERT INTO locations VALUES (?, ?, 1)',
                           [('/public/first', 'track'), ('/public/second', 'track')])
            before = list(db.iterdump())
            observation = _SQLiteObservation(span_context=callback)
            cursor = _ObservedConnection(db, observation).execute(SQL, ('track',))
            if failing_fetch == 3:
                self.assertEqual(next(cursor), ('/public/first',))
                self.assertEqual(next(cursor), ('/public/second',))
            # PEP 479 turns callback StopIteration into RuntimeError; this is
            # not legitimate exhaustion and must be recorded as failed.
            with self.assertRaisesRegex(RuntimeError, 'generator raised StopIteration'):
                if method == 'iteration':
                    next(cursor)
                else:
                    cursor.fetchone()
            raw = [span for span in observation._spans
                   if span['phase'] == 'selected_sql_fetch']
            correlated = [span for span in context['spans']
                          if span['phase'] == 'selected_sql_fetch']
            expected_prefix = ['partial', 'partial'] if failing_fetch == 3 else []
            self.assertEqual([span['status'] for span in raw], expected_prefix + ['failed'])
            # Failed factory/entry never yielded a correlated record. Do not
            # invent one merely to match the always-present raw measurement.
            expected_correlated = expected_prefix + (['failed'] if stage == 'exit' else [])
            self.assertEqual([span['status'] for span in correlated], expected_correlated)
            self.assertEqual(context['stack'], [])
            remaining = cursor.fetchall()
            if failing_fetch == 1:
                self.assertEqual(remaining, [('/public/second',)] if stage == 'exit' else
                                 [('/public/first',), ('/public/second',)])
            else:
                self.assertEqual(remaining, [])
            # Later successful drain may promote partial, never failed spans.
            self.assertEqual(raw[-1]['status'], 'failed')
            if stage == 'exit':
                self.assertEqual(correlated[-1]['status'], 'failed')
            with self.assertRaises(StopIteration):
                next(cursor)
            self.assertEqual(observation._spans[-1]['status'], 'ok')
            self.assertEqual(list(db.iterdump()), before)
            for records in (observation._spans, context['spans']):
                self.assertNotIn(private_error, repr(records))
                self.assertNotIn('/public/', repr(records))
                for span in records:
                    self.assertEqual(span['clock'], 'monotonic')
                    self.assertGreaterEqual(span['end_ms'], span['start_ms'])

    def test_callback_failure_on_fetchone(self):
        for stage in ('factory', 'entry', 'exit'):
            with self.subTest(stage=stage):
                self.exercise_callback_failure(stage, failing_fetch=1, method='fetchone')

    def test_callback_failure_on_first_iteration(self):
        for stage in ('factory', 'entry', 'exit'):
            with self.subTest(stage=stage):
                self.exercise_callback_failure(stage, failing_fetch=1)

    def test_callback_failure_on_terminal_iteration_does_not_certify_prior_steps(self):
        for stage in ('factory', 'entry', 'exit'):
            with self.subTest(stage=stage):
                self.exercise_callback_failure(stage, failing_fetch=3)

