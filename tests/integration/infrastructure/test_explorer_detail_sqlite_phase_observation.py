"""PR B RED: outward SQLite phases, not request-wall-time relabeling.

Only tiny public writer fixtures; no production changes or latency budgets.
Controls execute before the missing-span assertions, so setup/import failures
cannot masquerade as the intended RED. Proposed report contract is additive to
observe_sqlite().report(): spans carry SQL operation, phase, fetch_method,
clock/start/end/status (ok/failed/partial); no returned rows or arbitrary exception text.
"""
from contextlib import closing, contextmanager
import json
import math
from pathlib import Path
import sqlite3
import unittest
from unittest.mock import patch

from music_explorer.infrastructure.explorer_readonly import ReadOnlyExplorerSQLiteRepository
from tools.explorer_fixture_inspection import fingerprint_sqlite_files
from tools.explorer_http_diagnostic import run_public_http_diagnostic
from tools.explorer_http_sqlite_observation import observe_sqlite
from tools.explorer_synthetic_fixture import public_synthetic_fixture


class DetailSQLitePhaseObservationRedTests(unittest.TestCase):
    def assert_span(self, span):
        self.assertEqual(span['clock'], 'monotonic')
        self.assertIn(span['status'], ('ok', 'failed', 'partial'))
        for key in ('start_ms', 'end_ms'):
            self.assertIsNot(type(span[key]), bool)
            self.assertIsInstance(span[key], (float, int))
            self.assertTrue(math.isfinite(span[key]))
        self.assertGreaterEqual(span['end_ms'], span['start_ms'])

    def test_actual_http_execute_and_fetch_use_bound_udf_connection_without_wal_changes(self):
        evidence = {'queries': [], 'fetches': []}
        connect = sqlite3.connect

        class Cursor(sqlite3.Cursor):
            def fetchone(cursor):
                evidence['fetches'].append(('fetchone', cursor.sql))
                return super().fetchone()

            def fetchall(cursor):
                evidence['fetches'].append(('fetchall', cursor.sql))
                return super().fetchall()

        class Connection(sqlite3.Connection):
            def execute(connection, sql, parameters=()):
                cursor = connection.cursor(factory=Cursor)
                cursor.sql = sql
                cursor.execute(sql, parameters)
                if sql.startswith('EXPLAIN QUERY PLAN '):
                    # EQP must use the executing connection, including the
                    # repository-installed summary UDFs and real bindings.
                    evidence['queries'].append((id(connection), sql, list(parameters)))
                elif '_explorer_summary_' in sql:
                    evidence['queries'].append((id(connection), sql, list(parameters)))
                return cursor

        @contextmanager
        def fixture_factory(**options):
            with public_synthetic_fixture(**options) as fixture:
                path = Path(fixture['db_path'])
                # Keep an idle writer open to avoid checkpoint-on-close noise.
                with closing(connect(path)) as writer:
                    writer.execute('PRAGMA journal_mode=WAL')
                    writer.execute('PRAGMA wal_autocheckpoint=0')
                    writer.execute('UPDATE tracks SET size=size')
                    writer.commit()
                    evidence['before'] = fingerprint_sqlite_files(path)
                    evidence['path'] = str(path)
                    self.assertIsNotNone(evidence['before']['wal_sha256'])

                    def connection(database, *args, **kwargs):
                        self.assertIn('mode=ro', str(database))
                        self.assertNotIn('immutable=1', str(database))
                        kwargs['factory'] = Connection
                        return connect(database, *args, **kwargs)

                    with patch.object(sqlite3, 'connect', side_effect=connection):
                        yield fixture
                    evidence['after'] = fingerprint_sqlite_files(path)

        report = run_public_http_diagnostic(sample_count=1, timeout_seconds=5,
                                            fixture_factory=fixture_factory)
        self.assertTrue(report['requests'])
        self.assertTrue(all(request['status'] == 200 for request in report['requests']))
        self.assertEqual(evidence['before'], evidence['after'])
        self.assertIs(report['readonly']['unchanged'], True)
        plans = report['sqlite']['plans']
        summary = [plan for plan in plans if plan['operation'] == 'summary_page'][0]
        self.assertIn('_explorer_summary_', summary['sql'])
        self.assertTrue(summary['parameters'])
        executions = [(conn, sql, params) for conn, sql, params in evidence['queries']
                      if sql == summary['sql'] and params == summary['parameters']]
        self.assertTrue(executions)
        self.assertTrue(any((conn, 'EXPLAIN QUERY PLAN ' + sql, params)
                            in evidence['queries'] for conn, sql, params in executions))
        selected = {plan['operation']: plan for plan in plans}
        for operation, method in (('selected_track', 'fetchone'),
                                  ('selected_locations', 'fetchall')):
            self.assertIn((method, selected[operation]['sql']), evidence['fetches'])
        self.assertNotIn(evidence['path'], json.dumps(report))

        self.assertIn('spans', report['sqlite'],
                      'PR B missing actual SQLite execute/fetch spans; EQP is not drain timing')
        spans = report['sqlite']['spans']
        for operation, method in (('selected_track', 'fetchone'),
                                  ('selected_locations', 'fetchall')):
            with self.subTest(operation=operation):
                execute = [span for span in spans if span['operation'] == operation
                           and span['phase'] == 'selected_sql_execute']
                fetch = [span for span in spans if span['operation'] == operation
                         and span['phase'] == 'selected_sql_fetch' and span['fetch_method'] == method]
                self.assertTrue(execute)
                self.assertTrue(fetch, 'returning a bare cursor loses materialization work')
                for span in execute + fetch:
                    self.assert_span(span)
                    self.assertEqual(span['status'], 'ok')

    def test_partial_iteration_and_failed_execute_are_redacted_and_boundary_restores(self):
        original = ReadOnlyExplorerSQLiteRepository._connection
        sentinel = '/private/catalogue/secret-payload.sqlite'
        observation = None
        with public_synthetic_fixture() as fixture:
            path = Path(fixture['db_path'])
            before = fingerprint_sqlite_files(path)
            repository = ReadOnlyExplorerSQLiteRepository(str(path))
            with self.assertRaisesRegex(RuntimeError, 'owned lifecycle failure'):
                with observe_sqlite() as observation:
                    with repository._connection() as db:
                        handle = db.execute('SELECT track_id FROM locations WHERE available=1 '
                                            'ORDER BY track_id LIMIT 1').fetchone()[0]
                        cursor = db.execute('SELECT path FROM locations WHERE track_id=? '
                                            'AND available=1 ORDER BY path', (handle,))
                        # Stop before observing exhaustion: even a one-row result
                        # is partial until the caller requests the terminal step.
                        rows = [next(iter(cursor))]
                        cursor.close()
                        self.assertTrue(rows)
                        # A real SQLite binding error, not a fabricated clock or
                        # mocked cursor: the selected statement never completes.
                        with self.assertRaises(sqlite3.ProgrammingError):
                            db.execute('SELECT id,sha256,size FROM tracks WHERE id=?', ())
                    raise RuntimeError('owned lifecycle failure ' + sentinel)
            self.assertIs(ReadOnlyExplorerSQLiteRepository._connection, original)
            sql_report = observation.report(path)
            self.assertEqual(before, fingerprint_sqlite_files(path))
            self.assertNotIn(sentinel, json.dumps(sql_report))
            self.assertNotIn(str(path), json.dumps(sql_report))
            for row in rows:
                self.assertNotIn(row[0], json.dumps(sql_report), 'cursor payload must not publish')

        # Restore and fail-closed historical validation are independent controls.
        historical = {}

        @contextmanager
        def corrupt_fixture(**options):
            with public_synthetic_fixture(**options) as fixture:
                path = Path(fixture['db_path'])
                with closing(sqlite3.connect(path)) as db, db:
                    db.execute('UPDATE graph_feature_evidence SET fingerprint=? WHERE rowid='
                               '(SELECT max(rowid) FROM graph_feature_evidence WHERE is_current=0)',
                               ('0' * 64,))
                historical['before'] = fingerprint_sqlite_files(path)
                yield fixture
                historical['after'] = fingerprint_sqlite_files(path)

        rejected = run_public_http_diagnostic(sample_count=1, timeout_seconds=5,
                                              fixture_factory=corrupt_fixture)
        self.assertTrue(any(request['status'] is not None and request['status'] >= 400
                            for request in rejected['requests']))
        self.assertEqual(historical['before'], historical['after'])
        self.assertIs(ReadOnlyExplorerSQLiteRepository._connection, original)

        self.assertIn('spans', sql_report,
                      'PR B missing retained partial drain and failed-execute evidence')
        spans = sql_report['spans']
        iteration = [span for span in spans if span['operation'] == 'selected_locations'
                     and span['phase'] == 'selected_sql_fetch' and span['fetch_method'] == 'iteration'
                     and span['status'] == 'partial']
        failures = [span for span in spans if span['operation'] == 'selected_track'
                    and span['phase'] == 'selected_sql_execute' and span['status'] == 'failed']
        self.assertTrue(iteration)
        self.assertTrue(failures, 'failed execution must not disappear from the denominator')
        for span in iteration + failures:
            self.assert_span(span)


if __name__ == '__main__':
    unittest.main()
