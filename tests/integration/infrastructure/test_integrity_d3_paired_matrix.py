"""Bounded per-owner paired protocol matrix; all source rows are public SQLite."""
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
from time import monotonic
import unittest
from unittest.mock import patch

from music_analyzer.infrastructure.persistence import integrity
from music_analyzer.infrastructure.persistence.integrity_retained import scan_retained
from tests.integration.infrastructure.integrity_d3_public_fixture import create_public_retained_database

OWNERS = (('track_metadata', 'metadata', 'metadata_delivery_invalid', 3),
          ('stages', 'retained_stages', 'stage_delivery_invalid', 8))


class MatrixObservation:
    def __init__(self, table, count, mode='healthy', position=0):
        self.table, self.count, self.mode, self.position = table, count, mode, position
        self.opened = self.closed = self.fired = self.values = 0
        self.driver_errors = []

    def connection(self, raw):
        observation = self

        class Connection:
            def execute(self, sql, *params):
                cursor = raw.execute(sql, *params)
                observation.opened += 1
                envelope = (sql.startswith('SELECT CASE typeof(')
                            and f' FROM {observation.table} ORDER BY rowid' in sql)
                value = (sql.startswith('SELECT rowid,')
                         and f' FROM {observation.table} ORDER BY rowid' in sql)
                target = envelope if observation.mode.startswith('envelope') else value

                class Cursor:
                    ordinal = -1
                    last = None
                    fired = False

                    def fetchone(self):
                        row = cursor.fetchone()
                        if row is not None:
                            self.ordinal += 1
                        if target and not self.fired:
                            mode = observation.mode
                            if mode == 'envelope_invalid' and self.ordinal == observation.position:
                                observation.fired += 1
                                self.fired = True
                                return (.5,) + row[1:]
                            if mode.endswith('_missing') and self.ordinal == observation.count - 1:
                                observation.fired += 1
                                self.fired = True
                                return None
                            if row is None and mode.endswith('_duplicate'):
                                observation.fired += 1
                                self.fired = True
                                return self.last
                            if row is None and mode.endswith('_driver'):
                                observation.fired += 1
                                self.fired = True
                                cursor.close()
                                try:
                                    return cursor.fetchone()
                                except sqlite3.ProgrammingError as error:
                                    observation.driver_errors.append(str(error))
                                    raise
                        self.last = row if row is not None else self.last
                        if value:
                            observation.values += int(row is not None)
                        return row

                    def close(self):
                        observation.closed += 1
                        return cursor.close()
                return Cursor()
        return Connection()


class PairedMatrix(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='paired-matrix-')
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / 'public.sqlite'
        create_public_retained_database(self.path, 6)
        with closing(sqlite3.connect(self.path)) as db:
            db.execute('PRAGMA foreign_keys=ON')
            track = 'sha256:' + '3' * 64
            db.execute('INSERT INTO tracks VALUES(?,?,?)', (track, '3' * 64, 103))
            db.execute('INSERT INTO track_metadata VALUES(?,?,?,?)', (track, '[]', '[]', '[]'))
            db.commit()

    def run_owner(self, table, owner, code, count, mode='healthy', position=0, cap=None):
        observed = MatrixObservation(table, count, mode, position)
        with closing(sqlite3.connect(self.path)) as raw:
            delivery = integrity.Delivery(observed.connection(raw), monotonic() + 10)
            with patch.object(integrity, 'MAX_ROWS', cap or 1_000_000):
                result, findings = scan_retained(delivery, owner)
        self.assertEqual(observed.opened, observed.closed)
        self.assertEqual(observed.fired, int(mode != 'healthy'))
        self.assertIsNone(delivery.first_error)
        self.assertEqual((result.state, result.count_precision), ('completed', 'exact'))
        self.assertTrue(all(f.count <= result.count for f in findings))
        return result, findings, observed, delivery

    def test_direct_firing_nonfiring_target_and_nontarget_controls(self):
        for table, owner, code, count in OWNERS:
            column = 'result' if table == 'stages' else 'common_json'
            for mode in ('healthy', 'envelope_invalid', 'envelope_missing', 'envelope_duplicate',
                         'value_missing', 'value_duplicate', 'envelope_driver', 'value_driver'):
                with self.subTest(owner=owner, mode=mode):
                    observed = MatrixObservation(table, count, mode)
                    target_envelope = mode.startswith('envelope')
                    sql = (f"SELECT CASE typeof({column}) WHEN 'text' THEN length(CAST({column} AS BLOB)) END,rowid,count(*) OVER() FROM {table} ORDER BY rowid"
                           if target_envelope else f'SELECT rowid,{column} FROM {table} ORDER BY rowid')
                    with closing(sqlite3.connect(self.path)) as raw:
                        db = observed.connection(raw)
                        cursor = db.execute(sql)
                        rows = []
                        try:
                            if mode.endswith('_driver'):
                                with self.assertRaises(sqlite3.ProgrammingError):
                                    while (row := cursor.fetchone()) is not None:
                                        rows.append(row)
                            else:
                                while (row := cursor.fetchone()) is not None:
                                    rows.append(row)
                                self.assertIsNone(cursor.fetchone())
                        finally:
                            cursor.close()
                        cursor = db.execute(f'SELECT count(*) FROM {table}')
                        self.assertEqual(cursor.fetchone(), (count,))
                        self.assertIsNone(cursor.fetchone())
                        cursor.close()
                        if mode == 'envelope_invalid':
                            self.assertEqual(rows[0][0], .5)
                            self.assertEqual(rows[1:], raw.execute(sql).fetchall()[1:])
                        elif not mode.endswith('_driver'):
                            expected = raw.execute(sql).fetchall()
                            if mode.endswith('_missing'):
                                expected = expected[:-1]
                            elif mode.endswith('_duplicate'):
                                expected = expected + [expected[-1]]
                            self.assertEqual(rows, expected)
                    self.assertEqual(observed.fired, int(mode != 'healthy'))
                    self.assertEqual(observed.opened, observed.closed)

    def test_first_middle_last_invalid_envelopes_abandon_without_catchup(self):
        for table, owner, code, count in OWNERS:
            for position in (0, count // 2, count - 1):
                for mode in ('healthy', 'envelope_invalid'):
                    with self.subTest(owner=owner, position=position, mode=mode):
                        result, findings, observed, delivery = self.run_owner(table, owner, code, count, mode, position)
                        self.assertEqual(result.count, count)
                        self.assertEqual([(f.code, f.count) for f in findings],
                                         [] if mode == 'healthy' else [(code, count - position)])
                        self.assertEqual(observed.values, count if mode == 'healthy' else position)
                        self.assertEqual(delivery.count, 2 * count if mode == 'healthy' else count + position)

    def test_missing_duplicate_envelope_and_value_eof_row_or_matrix(self):
        for table, owner, code, count in OWNERS:
            for mode in ('healthy', 'envelope_missing', 'envelope_duplicate', 'value_missing', 'value_duplicate'):
                with self.subTest(owner=owner, mode=mode):
                    result, findings, observed, delivery = self.run_owner(table, owner, code, count, mode)
                    expected = count - 1 if mode == 'envelope_missing' else count
                    self.assertEqual(result.count, expected)
                    self.assertEqual([(f.code, f.count) for f in findings], [] if mode == 'healthy' else [(code, 1)])
                    # Early envelopeEOF cannot authorize one further whole value.
                    self.assertEqual(observed.values, count - 1 if mode in ('envelope_missing', 'value_missing') else count)

    def test_exact_cap_for_healthy_invalid_and_terminal_matrix(self):
        for table, owner, code, count in OWNERS:
            for mode, cap in (('healthy', 2 * count), ('envelope_invalid', count),
                              ('envelope_missing', 2 * (count - 1)),
                              ('envelope_duplicate', 2 * count), ('value_missing', 2 * count - 1),
                              ('value_duplicate', 2 * count)):
                with self.subTest(owner=owner, mode=mode):
                    if mode.endswith('_missing'):
                        # This EOF is not yet provable from admitted cardinality.
                        # At an exhausted cap, refuse BEFORE fetching a row.
                        observed = MatrixObservation(table, count, mode)
                        with closing(sqlite3.connect(self.path)) as raw:
                            delivery = integrity.Delivery(observed.connection(raw), monotonic() + 10)
                            with patch.object(integrity, 'MAX_ROWS', cap):
                                with self.assertRaises(integrity.AdmissionStop) as caught:
                                    scan_retained(delivery, owner)
                        self.assertEqual(caught.exception.reason, 'row_limit')
                        self.assertEqual(delivery.count, cap)
                        self.assertEqual(delivery.retained_work[owner], count - 1)
                        self.assertEqual(observed.fired, 0)
                        self.assertEqual(observed.values, count - 1)
                        self.assertEqual(observed.opened, observed.closed)
                        continue
                    result, findings, observed, delivery = self.run_owner(table, owner, code, count, mode, cap=cap)
                    self.assertEqual(delivery.count, cap)
                    self.assertTrue(all(f.count <= result.count for f in findings))

    def test_real_closed_cursor_driver_errors_remain_operational_and_cleanup(self):
        for table, owner, code, count in OWNERS:
            for mode in ('envelope_driver', 'value_driver'):
                with self.subTest(owner=owner, mode=mode):
                    observed = MatrixObservation(table, count, mode)
                    with closing(sqlite3.connect(self.path)) as raw:
                        delivery = integrity.Delivery(observed.connection(raw), monotonic() + 10)
                        with self.assertRaises(sqlite3.ProgrammingError):
                            scan_retained(delivery, owner)
                    self.assertIsNotNone(delivery.first_error)
                    self.assertEqual(observed.driver_errors, ['Cannot operate on a closed cursor.'])
                    self.assertEqual(observed.opened, observed.closed)
                    self.assertEqual(observed.fired, 1)
                    self.assertEqual(delivery.retained_work[owner], count)

    def test_prior_content_findings_survive_later_abandonment_and_terminal_or(self):
        for table, owner, code, count in OWNERS:
            column = 'result' if table == 'stages' else 'common_json'
            prefix = 'stage' if table == 'stages' else 'metadata'
            with closing(sqlite3.connect(self.path)) as db:
                db.execute(f"UPDATE {table} SET {column}='not json' WHERE rowid=(SELECT min(rowid) FROM {table})")
                db.commit()
            for mode in ('envelope_invalid', 'envelope_duplicate', 'value_duplicate'):
                with self.subTest(owner=owner, mode=mode):
                    result, findings, observed, delivery = self.run_owner(table, owner, code, count, mode, position=count - 1)
                    self.assertEqual(result.count, count)
                    self.assertEqual([(f.code, f.count) for f in findings], [(prefix + '_json_invalid', 1), (code, 1)])
