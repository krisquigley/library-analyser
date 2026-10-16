"""Paired-stream admission regressions using public SQLite rows, not fake data."""
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
from time import monotonic
import unittest
from unittest.mock import patch

from music_analyzer.application.use_cases.check_integrity import CheckIntegrity
from music_analyzer.infrastructure.persistence import integrity
from music_analyzer.infrastructure.persistence.integrity_retained import scan_retained
from tests.integration.infrastructure.integrity_d3_public_fixture import create_public_retained_database


OWNERS = (('track_metadata', 'metadata', 'metadata_delivery_invalid', 2),
          ('stages', 'retained_stages', 'stage_delivery_invalid', 8))


class Observation:
    """Replace only first envelope size with .5; actual payloads are untouched.

    Optional terminal duplicate exercises Delivery's envelopeEOF mismatch, not
    an invented driver exception. Track payload admission to forbid catchup.
    """
    def __init__(self, table, inject=False, duplicate=False):
        self.real_connect = sqlite3.connect
        self.table, self.inject, self.duplicate = table, inject, duplicate
        self.fired = self.eof_fired = self.opened = self.closed = 0
        self.value_rows = 0

    def connect(self, *args, **kwargs):
        raw = self.real_connect(*args, **kwargs)
        observation = self

        class Connection:
            def execute(self, sql, *params):
                cursor = raw.execute(sql, *params)
                observation.opened += 1
                target = (sql.startswith('SELECT CASE typeof(')
                          and f' FROM {observation.table} ORDER BY rowid' in sql)
                value = (sql.startswith('SELECT rowid,')
                         and f' FROM {observation.table} ORDER BY rowid' in sql)

                class Cursor:
                    first = True
                    last = None
                    eof_fired = False

                    def fetchone(self):
                        row = cursor.fetchone()
                        if target and row is not None:
                            self.last = row
                            if self.first:
                                self.first = False
                                if observation.inject:
                                    observation.fired += 1
                                    return (.5,) + row[1:]
                        if target and row is None and observation.duplicate and not self.eof_fired:
                            self.eof_fired = True
                            observation.eof_fired += 1
                            return self.last
                        if value:
                            observation.value_rows += int(row is not None)
                        return row

                    def close(self):
                        observation.closed += 1
                        return cursor.close()

                    def __getattr__(self, name):
                        return getattr(cursor, name)
                return Cursor()

            def __getattr__(self, name):
                return getattr(raw, name)
        return Connection()


class PairedAlignment(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='paired-alignment-')
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / 'public.sqlite'
        create_public_retained_database(self.path, 6)

    def test_proxy_direct_firing_nonfiring_preserves_actual_values(self):
        for table, owner, code, count in OWNERS:
            for inject in (False, True):
                with self.subTest(table=table, inject=inject):
                    observation = Observation(table, inject)
                    with closing(observation.connect(self.path)) as db:
                        column = 'result' if table == 'stages' else 'common_json'
                        cursor = db.execute(f"SELECT CASE typeof({column}) WHEN 'text' THEN length(CAST({column} AS BLOB)) END,rowid FROM {table} ORDER BY rowid")
                        envelopes = list(iter(cursor.fetchone, None))
                        cursor.close()
                        cursor = db.execute(f'SELECT rowid,{column} FROM {table} ORDER BY rowid')
                        values = list(iter(cursor.fetchone, None))
                        cursor.close()
                        cursor = db.execute(f'SELECT count(*) FROM {table}')
                        self.assertEqual(cursor.fetchone(), (count,))
                        cursor.close()
                    with closing(sqlite3.connect(self.path)) as raw:
                        self.assertEqual(values, raw.execute(f'SELECT rowid,{column} FROM {table} ORDER BY rowid').fetchall())
                    self.assertEqual(len(values), count)
                    self.assertTrue(all(isinstance(row[1], str) for row in values))
                    self.assertEqual(len(envelopes), count)
                    self.assertEqual(envelopes[0][0], .5 if inject else len(values[0][1].encode('utf-8')))
                    self.assertEqual(observation.fired, int(inject))
                    self.assertEqual(observation.opened, observation.closed)

    def test_healthy_nonfiring_scans_are_identical(self):
        baseline = integrity.SQLiteIntegrityScanner().scan(str(self.path))
        for table, owner, code, count in OWNERS:
            observation = Observation(table)
            with patch.object(integrity.sqlite3, 'connect', observation.connect):
                scan = integrity.SQLiteIntegrityScanner().scan(str(self.path))
            self.assertEqual(scan, baseline)
            self.assertEqual(observation.fired, 0)
            self.assertEqual(observation.value_rows, count)
            self.assertEqual(observation.opened, observation.closed)

    def assert_bad_first(self, index):
        table, owner, code, count = OWNERS[index]
        observation = Observation(table, True)
        with patch.object(integrity.sqlite3, 'connect', observation.connect):
            report = CheckIntegrity(integrity.SQLiteIntegrityScanner()).execute(str(self.path))
        self.assertEqual(observation.fired, 1)
        self.assertEqual(observation.opened, observation.closed)
        self.assertEqual(report.stop_reason, 'scope_not_implemented')
        self.assertIsNotNone(report.schema_version)
        self.assertEqual([(f.check_id, f.code, f.count) for f in report.findings], [(owner, code, count)])
        # The conservative choice is to abandon; later envelopes cannot authorize
        # a stale whole payload or catchup of the unadmitted first payload.
        self.assertEqual(observation.value_rows, 0)

    def test_metadata_bad_first_envelope_does_not_misalign_or_overcount(self):
        self.assert_bad_first(0)

    def test_stage_bad_first_envelope_does_not_misalign_or_overcount(self):
        self.assert_bad_first(1)

    def test_sole_invalid_envelope_then_envelope_eof_is_one_row_or_finding(self):
        for table, owner, code, count in OWNERS:
            with self.subTest(owner=owner):
                with closing(sqlite3.connect(self.path)) as db:
                    db.execute(f'DELETE FROM {table} WHERE rowid != (SELECT min(rowid) FROM {table})')
                    db.commit()
                observation = Observation(table, True, True)
                with closing(observation.connect(self.path)) as db:
                    delivery = integrity.Delivery(db, monotonic() + 10)
                    result, findings = scan_retained(delivery, owner)
                self.assertEqual((observation.fired, observation.eof_fired), (1, 1))
                self.assertEqual(observation.opened, observation.closed)
                self.assertEqual((result.state, result.count, result.count_precision), ('completed', 1, 'exact'))
                self.assertEqual([(f.code, f.count) for f in findings], [(code, 1)])
                self.assertEqual(observation.value_rows, 0)
                self.assertIsNone(delivery.first_error)

    def test_later_bad_content_is_suppressed_after_alignment_is_abandoned(self):
        for table, owner, code, count in OWNERS:
            column = 'result' if table == 'stages' else 'common_json'
            with closing(sqlite3.connect(self.path)) as db:
                db.execute(f"UPDATE {table} SET {column}='not json' WHERE rowid=(SELECT max(rowid) FROM {table})")
                db.commit()
            observation = Observation(table, True)
            with closing(observation.connect(self.path)) as db:
                result, findings = scan_retained(integrity.Delivery(db, monotonic() + 10), owner)
            self.assertEqual(result.count, count)
            self.assertEqual([(f.code, f.count) for f in findings], [(code, count)])
            self.assertEqual(observation.value_rows, 0)
            self.assertEqual(observation.opened, observation.closed)
