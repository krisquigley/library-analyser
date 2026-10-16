"""Public SQLite cursor MemoryError is operational, never corruption evidence."""
import sqlite3
from unittest.mock import patch

from music_analyzer.infrastructure.persistence.integrity import SQLiteIntegrityScanner
from tests.integration.infrastructure.test_integrity_d3_metadata import MetadataCase, check


class MemoryCursor:
    def __init__(self, cursor, observation, target):
        self.cursor, self.observation, self.target = cursor, observation, target

    def fetchone(self):
        o = self.observation
        if self.target and o.after is not None and o.delivered == o.after and not o.fired:
            o.fired += 1
            raise MemoryError('PRIVATE injected allocation failure')
        row = self.cursor.fetchone()
        if self.target:
            o.delivered += int(row is not None)
            o.eof += int(row is None)
        return row

    def close(self):
        if self.target:
            self.observation.cursor_closes += 1
        self.cursor.close()

    def __getattr__(self, name):
        return getattr(self.cursor, name)


class MemoryConnection:
    def __init__(self, connection, observation):
        self.connection, self.observation = connection, observation

    def execute(self, sql, *args):
        text = ' '.join(sql.lower().split())
        target = text.startswith('select rowid,') and 'from ' + self.observation.table in text
        return MemoryCursor(self.connection.execute(sql, *args), self.observation, target)

    def close(self):
        self.observation.connection_closes += 1
        self.connection.close()

    def __getattr__(self, name):
        return getattr(self.connection, name)


class MemoryObservation:
    def __init__(self, table, after=None):
        self.real_connect = sqlite3.connect
        self.table, self.after = table, after
        self.connections = self.connection_closes = self.cursor_closes = 0
        self.delivered = self.eof = self.fired = 0

    def connect(self, *args, **kwargs):
        self.connections += 1
        return MemoryConnection(self.real_connect(*args, **kwargs), self)

    def scan(self, path):
        with patch('music_analyzer.infrastructure.persistence.integrity.sqlite3.connect', self.connect):
            return SQLiteIntegrityScanner().scan(str(path))


class MemoryControls(MetadataCase):
    def test_transparent_metadata_and_stage_value_streams_drain_and_cleanup(self):
        path = self.public(6)
        plain = SQLiteIntegrityScanner().scan(str(path))
        self.assertEqual(plain.stop_reason, 'scope_not_implemented')
        self.assertFalse(plain.findings)
        for table in ('track_metadata', 'stages'):
            with self.subTest(table=table):
                o = MemoryObservation(table)
                self.assertEqual(o.scan(path), plain)
                self.assertGreater(o.delivered, 1)
                self.assertGreater(o.eof, 0)
                self.assertGreater(o.cursor_closes, 0)
                self.assertEqual((o.connections, o.connection_closes, o.fired), (1, 1, 0))


class MemoryOperationalTests(MetadataCase):
    def test_value_allocation_failure_preserves_operational_prefix_and_cleanup(self):
        path = self.public(6)
        for table, owner in (('track_metadata', 'metadata'), ('stages', 'retained_stages')):
            for after in (0, 1):
                with self.subTest(table=table, after=after):
                    o = MemoryObservation(table, after)
                    escaped = None
                    try:
                        scan = o.scan(path)
                    except Exception as error:
                        escaped = type(error).__name__
                    self.assertEqual(o.fired, 1, 'public cursor fault must be reached')
                    self.assertEqual((o.connections, o.connection_closes), (1, 1))
                    self.assertGreater(o.cursor_closes, 0)
                    self.assertIsNone(escaped, 'allocation failure must become a sanitized read_error, not escape')
                    self.assertEqual(scan.stop_reason, 'read_error')
                    self.assertFalse(scan.implemented_scope_complete)
                    # Work counts only envelopes with reliable bounded value delivery.
                    self.assertEqual((check(scan, owner).state, check(scan, owner).count,
                                      check(scan, owner).count_precision), ('interrupted', after, 'lower_bound'))
                    self.assertEqual((check(scan, 'resource_access').state,
                                      check(scan, 'resource_access').count_precision), ('interrupted', 'lower_bound'))
                    self.assertEqual([(f.check_id, f.code, f.count_precision) for f in scan.findings],
                                     [('resource_access', 'read_failed', 'lower_bound')])
                    if owner == 'metadata':
                        self.assertEqual(check(scan, 'retained_stages').state, 'blocked')
                    else:
                        self.assertEqual((check(scan, 'metadata').state, check(scan, 'metadata').count_precision),
                                         ('completed', 'exact'))
                    self.assertNotIn('PRIVATE', repr(scan))
