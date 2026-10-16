"""Real schema6 relation evidence precedes semantic audio-row charging.

Tiny public fixture; sequential setup/scan connections. Proxies execute genuine
SQL and fail only the subsequent audio value fetch, never synthesize markers.
"""
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from music_analyzer.application.use_cases.check_integrity import CheckIntegrity
from music_analyzer.infrastructure.persistence.integrity import SQLiteIntegrityScanner
from tests.integration.infrastructure.analysis_historical_schema_fixture import create_historical_schema


class Cursor:
    def __init__(self, cursor, observation, target):
        self.cursor, self.observation, self.target = cursor, observation, target
        self.closed = 0

    def fetchone(self):
        if self.target and self.observation.action:
            self.observation.fired += 1
            if self.observation.action == 'cancel':
                raise KeyboardInterrupt('PRIVATE injected cancellation')
            raise sqlite3.OperationalError('PRIVATE injected audio read')
        return self.cursor.fetchone()

    def close(self):
        self.closed += 1
        self.cursor.close()

    def __getattr__(self, name):
        return getattr(self.cursor, name)


class Connection:
    def __init__(self, connection, observation):
        self.connection, self.observation = connection, observation
        self.closed = 0

    def execute(self, sql, *args):
        target = ' '.join(sql.lower().split()) == (
            'select duration_seconds,duration_source,status,reason from track_audio order by rowid')
        cursor = Cursor(self.connection.execute(sql, *args), self.observation, target)
        self.observation.cursors.append(cursor)
        self.observation.targets += int(target)
        return cursor

    def close(self):
        self.closed += 1
        self.connection.close()

    def __getattr__(self, name):
        return getattr(self.connection, name)


class Observation:
    def __init__(self, action):
        self.real_connect = sqlite3.connect
        self.action, self.fired, self.targets = action, 0, 0
        self.connections, self.cursors = [], []

    def connect(self, *args, **kwargs):
        connection = Connection(self.real_connect(*args, **kwargs), self)
        self.connections.append(connection)
        return connection


def core(result):
    return next(item for item in result.checks if item.check_id == 'core_rows')


class CoreRelationPrefixTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='integrity-core-prefix-')
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / 'public.sqlite'
        create_historical_schema(self.path, 6)
        with closing(sqlite3.connect(self.path)) as connection:
            connection.execute('INSERT INTO track_audio VALUES(?,?,?,?,?)',
                               ('sha256:' + '1' * 64, 180.0, 'mutagen', 'eligible', ''))
            connection.commit()
            self.assertEqual(connection.execute('SELECT count(*) FROM tracks').fetchone(), (0,))
            self.assertEqual(connection.execute('SELECT count(*) FROM track_audio').fetchone(), (1,))
            self.assertEqual(len(connection.execute('PRAGMA foreign_key_check').fetchall()), 1)

    def run_scan(self, action, application=False):
        observation = Observation(action)
        with patch('music_analyzer.infrastructure.persistence.integrity.sqlite3.connect', observation.connect):
            scanner = SQLiteIntegrityScanner()
            result = (CheckIntegrity(scanner).execute(str(self.path)) if application
                      else scanner.scan(str(self.path)))
        self.assertEqual((len(observation.connections), observation.connections[0].closed), (1, 1))
        self.assertTrue(observation.cursors)
        self.assertTrue(all(cursor.closed == 1 for cursor in observation.cursors))
        self.assertEqual((observation.targets, observation.fired), (1, int(bool(action))))
        self.assertNotIn('PRIVATE', repr(result))
        return result

    def assert_prefix(self, result, action):
        self.assertEqual(result.schema_version, 6, 'app must retain recognized schema, not sanitized fallback')
        self.assertEqual((core(result).state, core(result).count, core(result).count_precision),
                         ('interrupted', 0, 'lower_bound'))
        self.assertFalse(result.implemented_scope_complete)
        self.assertEqual(result.stop_reason, 'cancelled' if action == 'cancel' else 'read_error')
        self.assertEqual([(f.code, f.severity, f.count, f.count_precision)
                          for f in result.findings if f.check_id == 'core_rows'],
                         [('track_audio_orphan', 'corruption', 1, 'lower_bound')])
        self.assertIn('cancelled' if action == 'cancel' else 'read_failed',
                      [f.code for f in result.findings if f.check_id == 'resource_access'])

    def test_nonfiring_real_orphan_control_reaches_completed_audio_rows(self):
        scan = self.run_scan(None)
        report = self.run_scan(None, application=True)
        self.assertEqual((scan.schema_version, report.schema_version), (6, 6))
        self.assertEqual((core(scan).state, core(scan).count, core(scan).count_precision),
                         ('completed', 1, 'exact'))
        self.assertEqual(report.checks, scan.checks)
        self.assertEqual(report.findings, scan.findings)
        self.assertIn(('track_audio_orphan', 1, 'exact'),
                      [(f.code, f.count, f.count_precision) for f in scan.findings])
        self.assertEqual((report.status, report.exit_code, report.complete), ('corrupt', 1, True))

    def test_read_failure_retains_real_orphan_prefix_through_application(self):
        scan = self.run_scan('read')
        self.assert_prefix(scan, 'read')
        report = self.run_scan('read', application=True)
        self.assert_prefix(report, 'read')
        self.assertEqual((report.status, report.exit_code, report.complete), ('incomplete', 4, False))
        self.assertEqual((report.coverage_revision, report.required_scope_revision), ('D3', 'P7-1'))
        self.assertEqual((report.checks, report.findings), (scan.checks, scan.findings))

    def test_cancellation_retains_prefix_and_cancellation_precedence(self):
        scan = self.run_scan('cancel')
        self.assert_prefix(scan, 'cancel')
        report = self.run_scan('cancel', application=True)
        self.assert_prefix(report, 'cancel')
        self.assertEqual((report.exit_code, report.complete), (130, False))
        self.assertEqual((report.checks, report.findings), (scan.checks, scan.findings))
