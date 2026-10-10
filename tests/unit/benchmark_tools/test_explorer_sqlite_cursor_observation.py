"""Cursor adapter contracts use real in-memory SQLite, not result payload reports."""
from contextlib import contextmanager
import sqlite3
import unittest

from tools.explorer_http_sqlite_observation import _ObservedConnection, _SQLiteObservation


SQL = 'SELECT path FROM locations WHERE track_id=? AND available=1 ORDER BY path'


class SQLiteCursorObservationTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(':memory:')
        self.addCleanup(self.db.close)
        self.db.execute('CREATE TABLE locations(path, track_id, available)')
        self.db.executemany('INSERT INTO locations VALUES (?, ?, 1)',
                            [('private-a', 'id'), ('private-b', 'id')])

    def test_actual_http_selected_stage_metadata_override_and_audio_are_attributed(self):
        from tools.explorer_http_diagnostic import run_public_http_diagnostic
        report = run_public_http_diagnostic(sample_count=1)
        sql = report['sqlite']
        plans = {plan['operation']: plan for plan in sql['plans']}
        for operation, fetch_method in (
                ('selected_stage_sizes', 'iteration'),
                ('selected_stage_payload', 'fetchone'),
                ('selected_overrides', 'iteration'),
                ('selected_metadata', 'fetchone'),
                ('selected_audio', 'fetchone')):
            with self.subTest(operation=operation):
                self.assertIn(operation, plans)
                self.assertTrue(plans[operation]['parameters'])
                self.assertTrue(plans[operation]['rows'])
                spans = [span for span in sql['spans'] if span['operation'] == operation]
                self.assertTrue(any(span['phase'] == 'selected_sql_execute' for span in spans))
                self.assertTrue(any(span['phase'] == 'observer_explain' for span in spans))
                self.assertTrue(any(span['phase'] == 'selected_sql_fetch' and
                                    span['fetch_method'] == fetch_method for span in spans))
                self.assertTrue(all(span['status'] == 'ok' for span in spans))
        self.assertTrue(report['readonly']['unchanged'])

    def test_phase_context_encloses_execute_and_each_actual_fetch(self):
        calls = []

        @contextmanager
        def context(phase):
            calls.append(('start', phase))
            try:
                yield
            finally:
                calls.append(('end', phase))

        observation = _SQLiteObservation(span_context=context)
        cursor = _ObservedConnection(self.db, observation).execute(SQL, ('id',))
        self.assertEqual(len(cursor.fetchmany(1)), 1)
        self.assertEqual(len(cursor.fetchall()), 1)
        self.assertEqual(calls, [('start', 'selected_sql_execute'),
                                 ('end', 'selected_sql_execute'),
                                 ('start', 'observer_explain'),
                                 ('end', 'observer_explain'),
                                 ('start', 'selected_sql_fetch'),
                                 ('end', 'selected_sql_fetch'),
                                 ('start', 'selected_sql_fetch'),
                                 ('end', 'selected_sql_fetch')])

    def test_partial_iteration_status_propagates_and_exhaustion_finishes_context(self):
        records = []

        @contextmanager
        def context(phase):
            record = {'phase': phase, 'status': 'ok'}
            records.append(record)
            yield record

        observation = _SQLiteObservation(span_context=context)
        cursor = _ObservedConnection(self.db, observation).execute(SQL, ('id',))
        next(cursor)
        self.assertEqual(records[-1]['status'], 'partial')
        self.assertEqual(len(list(cursor)), 1)
        self.assertTrue(all(record['status'] == 'ok' for record in records))
        eqp = [span for span in observation._spans if span['phase'] == 'observer_explain']
        self.assertEqual(len(eqp), 1)
        self.assertEqual(eqp[0]['status'], 'ok')

    def test_mixed_fetch_with_remaining_rows_only_fetchall_certifies_exhaustion(self):
        for method, args, expected in (('fetchone', (), 'partial'),
                                       ('fetchmany', (1,), 'partial'),
                                       ('fetchall', (), 'ok')):
            with self.subTest(method=method):
                records = []

                @contextmanager
                def context(phase):
                    record = {'phase': phase, 'status': 'ok'}
                    records.append(record)
                    yield record

                observation = _SQLiteObservation(span_context=context)
                cursor = _ObservedConnection(self.db, observation).execute(SQL, ('id',))
                next(cursor)
                self.assertTrue(getattr(cursor, method)(*args))
                iteration = [span for span in observation._spans
                             if span.get('fetch_method') == 'iteration'][0]
                self.assertEqual(iteration['status'], expected)
                self.assertEqual(records[2]['status'], expected)
                cursor.close()

    def test_eqp_failure_keeps_completed_execute_and_failed_observer_cost(self):
        class FailingPlanConnection:
            def execute(proxy, sql, parameters=()):
                if sql.startswith('EXPLAIN QUERY PLAN '):
                    raise sqlite3.OperationalError('private failure must not be published')
                return self.db.execute(sql, parameters)

        observation = _SQLiteObservation()
        with self.assertRaises(sqlite3.OperationalError):
            _ObservedConnection(FailingPlanConnection(), observation).execute(SQL, ('id',))
        self.assertEqual([(span['phase'], span['status']) for span in observation._spans],
                         [('selected_sql_execute', 'ok'), ('observer_explain', 'failed')])
        self.assertNotIn('private', repr(observation._spans))

    def test_exhaustion_finishes_iteration_but_closed_fetch_failure_is_retained(self):
        observation = _SQLiteObservation()
        cursor = _ObservedConnection(self.db, observation).execute(SQL, ('id',))
        self.assertEqual(len(list(cursor)), 2)
        self.assertTrue(all(span['status'] == 'ok' for span in observation._spans))
        cursor.close()
        with self.assertRaises(sqlite3.ProgrammingError):
            cursor.fetchone()
        self.assertEqual(observation._spans[-1]['status'], 'failed')
        self.assertEqual(observation._spans[-1]['fetch_method'], 'fetchone')
        self.assertNotIn('private', repr(observation._spans))
