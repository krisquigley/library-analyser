"""Unexpected retained EOF delivery is owner-invalid, not a driver failure."""
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from music_analyzer.infrastructure.persistence import integrity
from tests.integration.infrastructure.integrity_d3_public_fixture import create_public_retained_database


class EOFCursor:
    def __init__(self, raw, observation, target):
        self.raw, self.observation, self.target = raw, observation, target
        self.last = None
        self.fired = False

    def fetchone(self):
        row = self.raw.fetchone()
        if self.target:
            if row is not None:
                self.last = row
            elif not self.fired and self.observation.mode != 'healthy':
                self.fired = True
                self.observation.fired += 1
                if self.observation.mode == 'read_error':
                    raise sqlite3.OperationalError('public EOF read failure')
                return self.last
        return row

    def close(self):
        self.observation.closed += 1
        return self.raw.close()

    def __getattr__(self, name):
        return getattr(self.raw, name)


class EOFConnection:
    def __init__(self, raw, observation):
        self.raw, self.observation = raw, observation

    def execute(self, sql, *args):
        cursor = self.raw.execute(sql, *args)
        self.observation.opened += 1
        target = (sql.startswith('SELECT rowid,') and
                  f'FROM {self.observation.table} ORDER BY rowid' in sql)
        return EOFCursor(cursor, self.observation, target)

    def __getattr__(self, name):
        return getattr(self.raw, name)


class Observation:
    def __init__(self, table, mode):
        self.real_connect = sqlite3.connect
        self.table, self.mode = table, mode
        self.fired = self.opened = self.closed = 0

    def connect(self, *args, **kwargs):
        return EOFConnection(self.real_connect(*args, **kwargs), self)


class RetainedEOF(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='retained-eof-')
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / 'public.sqlite'
        create_public_retained_database(self.path, 6)

    def test_direct_firing_nonfiring_and_nontarget_controls(self):
        for table, columns, count in (
                ('track_metadata', 'common_json,tags_json,warnings_json', 2),
                ('stages', 'stage,result', 8)):
            for mode in ('healthy', 'duplicate'):
                with self.subTest(table=table, mode=mode):
                    observation = Observation(table, mode)
                    with closing(observation.connect(self.path)) as db:
                        cursor = db.execute(f'SELECT rowid,{columns} FROM {table} ORDER BY rowid')
                        rows = []
                        while (row := cursor.fetchone()) is not None:
                            rows.append(row)
                        self.assertIsNone(cursor.fetchone())
                        cursor.close()
                        self.assertEqual(len(rows), count + (mode == 'duplicate'))
                        if mode == 'duplicate':
                            self.assertEqual(rows[-1], rows[-2])
                        cursor = db.execute(f'SELECT count(*) FROM {table}')
                        self.assertEqual(cursor.fetchone(), (count,))
                        self.assertIsNone(cursor.fetchone())
                        cursor.close()
                    self.assertEqual(observation.fired, int(mode == 'duplicate'))
                    self.assertEqual(observation.opened, observation.closed)

    def test_healthy_wrappers_equal_unwrapped_at_shared_exact_cap(self):
        baseline = integrity.SQLiteIntegrityScanner().scan(str(self.path))
        self.assertEqual(baseline.findings, ())
        for table in ('track_metadata', 'stages'):
            for cap in (1_000_000, 217):
                with self.subTest(table=table, cap=cap):
                    observation = Observation(table, 'healthy')
                    with patch.object(integrity.sqlite3, 'connect', observation.connect), patch.object(integrity, 'MAX_ROWS', cap):
                        self.assertEqual(integrity.SQLiteIntegrityScanner().scan(str(self.path)), baseline)
                    self.assertEqual(observation.fired, 0)
                    self.assertEqual(observation.opened, observation.closed)

    def assert_eof_scan(self, table, owner, count, mode):
        for cap in (1_000_000, 217):
            with self.subTest(table=table, cap=cap, mode=mode):
                observation = Observation(table, mode)
                deliveries = []
                class ObservedDelivery(integrity.Delivery):
                    def __init__(self, *args):
                        super().__init__(*args)
                        deliveries.append(self)
                with patch.object(integrity.sqlite3, 'connect', observation.connect), patch.object(integrity, 'MAX_ROWS', cap), patch.object(integrity, 'Delivery', ObservedDelivery):
                    scan = integrity.SQLiteIntegrityScanner().scan(str(self.path))
                self.assertEqual(observation.fired, 1)
                self.assertEqual(observation.opened, observation.closed)
                result = next(c for c in scan.checks if c.check_id == owner)
                actual = [(f.check_id, f.code, f.count, f.count_precision) for f in scan.findings]
                if mode == 'read_error':
                    self.assertEqual(scan.stop_reason, 'read_error')
                    self.assertEqual((result.state, result.count, result.count_precision), ('interrupted', count, 'lower_bound'))
                    self.assertEqual(actual, [('resource_access', 'read_failed', 1, 'lower_bound')])
                    self.assertIsNotNone(deliveries[-1].first_error)
                else:
                    self.assertEqual(scan.stop_reason, 'scope_not_implemented')
                    self.assertEqual((result.state, result.count, result.count_precision), ('completed', count, 'exact'))
                    code = 'stage_delivery_invalid' if owner == 'retained_stages' else 'metadata_delivery_invalid'
                    self.assertEqual(actual, [(owner, code, 1, 'exact')])
                    self.assertIsNone(deliveries[-1].first_error)
                    self.assertEqual(deliveries[-1].count, 217)

    def test_metadata_unexpected_eof_delivery_is_owner_invalid(self):
        self.assert_eof_scan('track_metadata', 'metadata', 2, 'duplicate')

    def test_stage_unexpected_eof_delivery_is_owner_invalid(self):
        self.assert_eof_scan('stages', 'retained_stages', 8, 'duplicate')

    def test_real_eof_read_errors_remain_operational(self):
        self.assert_eof_scan('track_metadata', 'metadata', 2, 'read_error')
        self.assert_eof_scan('stages', 'retained_stages', 8, 'read_error')


# Size-envelope EOF regression (value-stream coverage above remains unchanged).
from time import monotonic
from music_analyzer.infrastructure.persistence.integrity_retained import scan_retained

OWNERS = (('track_metadata', 'metadata', 'metadata_delivery_invalid', 2),
          ('stages', 'retained_stages', 'stage_delivery_invalid', 8))


class EnvelopeObservation:
    """Only size-envelope EOF is perturbed; all values and other SQL delegate.

    The driver control closes the real cursor at EOF then calls its fetchone:
    sqlite3 itself raises ProgrammingError, not a proxy-authored exception.
    """
    def __init__(self, table, mode):
        self.real_connect = sqlite3.connect
        self.table, self.mode = table, mode
        self.opened = self.closed = self.fired = 0
        self.envelope_rows = self.value_rows = self.envelope_eof = 0
        self.driver_errors = []

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
                    last = None
                    fired = False

                    def fetchone(self):
                        row = cursor.fetchone()
                        if target:
                            observation.envelope_rows += int(row is not None)
                            if row is not None:
                                self.last = row
                            else:
                                observation.envelope_eof += 1
                                if not self.fired and observation.mode != 'healthy':
                                    self.fired = True
                                    observation.fired += 1
                                    if observation.mode == 'driver':
                                        cursor.close()
                                        try:
                                            return cursor.fetchone()
                                        except sqlite3.ProgrammingError as error:
                                            observation.driver_errors.append(str(error))
                                            raise
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


class RetainedEnvelopeEOF(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / 'public.sqlite'
        create_public_retained_database(self.path, 6)

    def scan(self, table, mode):
        observed = EnvelopeObservation(table, mode)
        with patch.object(integrity.sqlite3, 'connect', observed.connect):
            result = integrity.SQLiteIntegrityScanner().scan(str(self.path))
        self.assertEqual(observed.opened, observed.closed)
        return result, observed

    def test_direct_target_nontarget_eof_and_real_driver_controls(self):
        for table, owner, code, count in OWNERS:
            column = 'result' if table == 'stages' else 'common_json'
            for mode in ('healthy', 'duplicate', 'driver'):
                with self.subTest(table=table, mode=mode):
                    observed = EnvelopeObservation(table, mode)
                    with closing(observed.connect(self.path)) as db:
                        cursor = db.execute(f'SELECT CASE typeof({column}) WHEN \'text\' THEN 1 ELSE 0 END FROM {table} ORDER BY rowid')
                        rows = []
                        try:
                            if mode == 'driver':
                                with self.assertRaises(sqlite3.ProgrammingError):
                                    while (row := cursor.fetchone()) is not None:
                                        rows.append(row)
                            else:
                                while (row := cursor.fetchone()) is not None:
                                    rows.append(row)
                                self.assertIsNone(cursor.fetchone())
                        finally:
                            cursor.close()
                        cursor = db.execute('SELECT status FROM runs')
                        self.assertEqual(len(list(iter(cursor.fetchone, None))), 8)
                        cursor.close()
                    self.assertEqual(len(rows), count + (mode == 'duplicate'))
                    self.assertEqual(observed.fired, int(mode != 'healthy'))
                    self.assertEqual(bool(observed.driver_errors), mode == 'driver')
                    self.assertEqual(observed.opened, observed.closed)

    def test_healthy_wrapper_is_transparent_for_both_owners(self):
        plain = integrity.SQLiteIntegrityScanner().scan(str(self.path))
        for table, owner, code, count in OWNERS:
            with self.subTest(owner=owner):
                scan, observed = self.scan(table, 'healthy')
                self.assertEqual(scan, plain)
                self.assertEqual((observed.envelope_rows, observed.value_rows, observed.fired), (count, count, 0))

    def assert_owner_duplicate(self, index):
        table, owner, code, count = OWNERS[index]
        scan, observed = self.scan(table, 'duplicate')
        self.assertEqual((observed.fired, observed.envelope_rows, observed.value_rows), (1, count, count))
        result = next(item for item in scan.checks if item.check_id == owner)
        self.assertEqual((result.state, result.count, result.count_precision), ('completed', count, 'exact'))
        self.assertEqual([(f.check_id, f.code, f.count, f.count_precision) for f in scan.findings],
                         [(owner, code, 1, 'exact')])
        self.assertEqual(scan.stop_reason, 'scope_not_implemented')
        self.assertTrue(scan.implemented_scope_complete)

    def test_metadata_duplicate_envelope_eof_is_owner_finding(self):
        self.assert_owner_duplicate(0)

    def test_stages_duplicate_envelope_eof_is_owner_finding(self):
        self.assert_owner_duplicate(1)

    def test_real_sqlite_driver_failure_remains_operational(self):
        for table, owner, code, count in OWNERS:
            with self.subTest(owner=owner):
                scan, observed = self.scan(table, 'driver')
                self.assertEqual(observed.fired, 1)
                self.assertEqual(observed.driver_errors, ['Cannot operate on a closed cursor.'])
                self.assertEqual(scan.stop_reason, 'read_error')
                result = next(item for item in scan.checks if item.check_id == owner)
                self.assertEqual((result.state, result.count, result.count_precision), ('interrupted', count, 'lower_bound'))
                self.assertFalse(any(f.check_id == owner for f in scan.findings))

    def test_exact_cap_presence_does_not_admit_or_count_extra_envelope(self):
        for table, owner, code, count in OWNERS:
            charges = []
            for mode in ('healthy', 'duplicate'):
                with self.subTest(owner=owner, mode=mode):
                    observed = EnvelopeObservation(table, mode)
                    with closing(observed.connect(self.path)) as db:
                        delivery = integrity.Delivery(db, monotonic() + 10)
                        with patch.object(integrity, 'MAX_ROWS', 2 * count):
                            result, findings = scan_retained(delivery, owner)
                        self.assertEqual((result.state, result.count, result.count_precision), ('completed', count, 'exact'))
                        self.assertEqual(delivery.count, 2 * count)
                        self.assertEqual([(f.code, f.count) for f in findings], [] if mode == 'healthy' else [(code, 1)])
                        charges.append(delivery.utf8_bytes)
                    self.assertEqual(observed.opened, observed.closed)
                    self.assertEqual((observed.envelope_rows, observed.value_rows), (count, count))
                    self.assertEqual(observed.fired, int(mode == 'duplicate'))
            if len(charges) == 2:
                self.assertEqual(charges[0], charges[1])
            observed = EnvelopeObservation(table, 'duplicate')
            with closing(observed.connect(self.path)) as db:
                delivery = integrity.Delivery(db, monotonic() + 10)
                with patch.object(integrity, 'MAX_ROWS', 2 * count - 1):
                    with self.assertRaises(integrity.AdmissionStop) as caught:
                        scan_retained(delivery, owner)
                self.assertEqual(caught.exception.reason, 'row_limit')
                self.assertEqual(delivery.count, 2 * count - 1)
                self.assertEqual(delivery.retained_work[owner], count - 1)
            self.assertEqual(observed.opened, observed.closed)
            self.assertEqual(observed.fired, 0)
            self.assertEqual(observed.value_rows, count - 1)
