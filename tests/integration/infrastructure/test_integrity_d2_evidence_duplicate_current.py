"""Duplicate-current aggregate is proxy-only under genuine unique schema."""
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from music_analyzer.infrastructure.persistence.integrity import SQLiteIntegrityScanner
from tests.integration.infrastructure.integrity_d2_evidence_public_fixture import create_public_evidence_database

SQL = ('SELECT 1 AS marker FROM graph_feature_evidence WHERE is_current=1 '
       'GROUP BY track_id HAVING count(*)>1')


class DuplicateProxy:
    def __init__(self, enabled):
        self.enabled = enabled
        self.real_connect = sqlite3.connect
        self.delivered = 0

    def connect(self, *args, **kwargs):
        return ProxyConnection(self.real_connect(*args, **kwargs), self)


class ProxyConnection:
    def __init__(self, raw, proxy):
        self.raw, self.proxy = raw, proxy

    def execute(self, sql, params=()):
        cursor = self.raw.execute(sql, params)
        if self.proxy.enabled and SQL in sql:
            return ProxyCursor(cursor, self.proxy, sql != SQL)
        return cursor

    def __getattr__(self, name):
        return getattr(self.raw, name)


class ProxyCursor:
    def __init__(self, raw, proxy, preflight):
        self.raw, self.proxy, self.preflight = raw, proxy, preflight
        self.pending = True

    def fetchone(self):
        if self.pending:
            self.pending = False
            # One violating track, not n-1 occurrences. No persisted drift.
            if not self.preflight:
                self.proxy.delivered += 1
            return (None,) if self.preflight else (1,)
        return self.raw.fetchone()

    def __getattr__(self, name):
        return getattr(self.raw, name)


class IntegrityDuplicateCurrentControls(unittest.TestCase):
    def test_healthy_and_firing_aggregate_proxy(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'public.sqlite'
            create_public_evidence_database(path, 10)
            for enabled in (False, True):
                proxy = DuplicateProxy(enabled)
                with closing(proxy.connect(path)) as db, closing(db.execute(SQL)) as cursor:
                    self.assertEqual(cursor.fetchone(), (1,) if enabled else None)
                    self.assertIsNone(cursor.fetchone())
                self.assertEqual(proxy.delivered, int(enabled))


class IntegrityDuplicateCurrent(unittest.TestCase):
    def test_one_link_occurrence_per_proxy_violating_track_no_semantic_inflation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'public.sqlite'
            create_public_evidence_database(path, 10)
            proxy = DuplicateProxy(True)
            with patch('sqlite3.connect', proxy.connect):
                scan = SQLiteIntegrityScanner().scan(str(path))
            self.assertEqual([(f.check_id, f.code, f.count, f.count_precision) for f in scan.findings],
                             [('current_evidence', 'evidence_link_invalid', 1, 'exact')])
            self.assertEqual(proxy.delivered, 1, 'Actual fixed aggregate value cursor must fire')
            self.assertEqual([(c.state, c.count, c.count_precision) for c in scan.checks
                              if c.check_id in ('current_evidence', 'historical_evidence')],
                             [('completed', 2, 'exact')] * 2)
            self.assertTrue(scan.implemented_scope_complete)
