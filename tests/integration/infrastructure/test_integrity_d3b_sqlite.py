"""D3b physical/FK contract; synthetic marker streams are not disk corruption.

Controls execute genuine SQL in a pinned snapshot; enabled proxies replace only
bounded marker records. Non-target statements always forward to real SQLite.
"""
from contextlib import closing, ExitStack
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

from music_analyzer.infrastructure.persistence.integrity import SQLiteIntegrityScanner
from tests.integration.infrastructure.integrity_d1_public_fixture import create_public_core_database
from tests.integration.infrastructure.test_integrity_d3b_sqlite_controls import (
    PHYSICAL_MARKER as PHYSICAL, FK_MARKER as FOREIGN_KEYS,
)
MODULE = 'music_analyzer.infrastructure.persistence.integrity.'


class MarkerCursor:
    def __init__(self, cursor, observation, owner, preflight):
        self.cursor = cursor
        self.observation = observation
        self.owner = owner
        self.preflight = preflight
        self.fetched = 0
        self.eof = 0
        self.closed = 0
        self.rows = None
        if owner == observation.target and observation.records is not None:
            records = observation.records
            self.rows = iter([(None, len(records)) for _ in records] if preflight else records)

    def fetchone(self):
        o = self.observation
        if self.owner == o.target and not self.preflight and self.fetched == o.after:
            if o.action == 'read':
                o.fired += 1
                raise sqlite3.OperationalError('PRIVATE diagnostic path rowid SQL')
            if o.action == 'cancel':
                o.fired += 1
                raise KeyboardInterrupt('PRIVATE cancel')
            if o.action == 'deadline':
                o.fired += 1
                o.now = 1000
        row = self.cursor.fetchone() if self.rows is None else next(self.rows, None)
        if row is None:
            self.eof += 1
        else:
            self.fetched += 1
            o.deliveries += 1
        return row

    def close(self):
        self.closed += 1
        self.cursor.close()
        o = self.observation
        if self.owner == o.target and not self.preflight and o.close_failure:
            o.close_fired += 1
            raise sqlite3.OperationalError('PRIVATE cursor cleanup')


class MarkerConnection:
    def __init__(self, connection, observation):
        self.connection = connection
        self.observation = observation
        self.closed = False
        connection.set_trace_callback(observation.trace.append)

    def __getattr__(self, name):
        return getattr(self.connection, name)

    def execute(self, sql, *args):
        o = self.observation
        # Match only full supported table-valued PRAGMA spellings, not schema's
        # pragma_foreign_key_list or unrelated SELECTs. Always execute real SQL.
        owner = ('sqlite_physical' if 'pragma_integrity_check' in sql.lower()
                 else 'sqlite_foreign_keys' if 'pragma_foreign_key_check' in sql.lower()
                 else None)
        preflight = 'count(*) OVER()' in sql
        cursor = self.connection.execute(sql, *args)
        if owner:
            o.hits[owner] += 1
            o.starts.setdefault(owner, o.deliveries)
        else:
            o.non_target += 1
        wrapped = MarkerCursor(cursor, o, owner, preflight)
        o.cursors.append(wrapped)
        return wrapped

    def close(self):
        self.closed = True
        self.connection.close()
        if self.observation.late_deadline:
            self.observation.now = 1000
        if self.observation.final_failure:
            self.observation.final_fired += 1
            raise sqlite3.OperationalError('PRIVATE final cleanup')


class MarkerObservation:
    def __init__(self, target=None, records=None, action=None, after=1,
                 close_failure=False, final_failure=False, late_deadline=False):
        self.real_connect = sqlite3.connect
        self.target, self.records, self.action, self.after = target, records, action, after
        self.close_failure, self.final_failure = close_failure, final_failure
        self.late_deadline = late_deadline
        self.now = 0
        self.hits = dict(sqlite_physical=0, sqlite_foreign_keys=0)
        self.starts = {}
        self.deliveries = self.non_target = self.fired = self.close_fired = self.final_fired = 0
        self.connections, self.cursors, self.trace = [], [], []

    def connect(self, database, **kwargs):
        connection = MarkerConnection(self.real_connect(database, **kwargs), self)
        self.connections.append(connection)
        return connection


def state(result, owner):
    item = next(c for c in result.checks if c.check_id == owner)
    return item.state, item.count, item.count_precision


def findings(result, owner):
    return [(f.code, f.severity, f.count, f.count_precision)
            for f in result.findings if f.check_id == owner]


class CountedAssertions(unittest.TestCase):
    assertions = 0

    def assertEqual(self, *args, **kwargs):
        type(self).assertions += 1
        return super().assertEqual(*args, **kwargs)

    def assertTrue(self, *args, **kwargs):
        type(self).assertions += 1
        return super().assertTrue(*args, **kwargs)

    def assertFalse(self, *args, **kwargs):
        type(self).assertions += 1
        return super().assertFalse(*args, **kwargs)

    def assertIn(self, *args, **kwargs):
        type(self).assertions += 1
        return super().assertIn(*args, **kwargs)

    def assertNotIn(self, *args, **kwargs):
        type(self).assertions += 1
        return super().assertNotIn(*args, **kwargs)

    def assertGreater(self, *args, **kwargs):
        type(self).assertions += 1
        return super().assertGreater(*args, **kwargs)

    def assertIsNone(self, *args, **kwargs):
        type(self).assertions += 1
        return super().assertIsNone(*args, **kwargs)

    def assertRaises(self, *args, **kwargs):
        type(self).assertions += 1
        return super().assertRaises(*args, **kwargs)

    @classmethod
    def tearDownClass(cls):
        print(f'{cls.__name__}: executed assertions={cls.assertions}', file=sys.stderr)


class IntegrityD3bSQLiteControls(CountedAssertions):
    def test_transparent_and_injected_markers_forward_non_targets_and_prove_eof(self):
        for owner, sql, actual in (('sqlite_physical', PHYSICAL, [(1,)]),
                                   ('sqlite_foreign_keys', FOREIGN_KEYS, [])):
            for records in (None, [(0,)], [(0,)] * 99, [(0,)] * 100):
                with self.subTest(owner=owner, count=None if records is None else len(records)):
                    with tempfile.TemporaryDirectory() as td:
                        path = Path(td) / 'public.sqlite'
                        create_public_core_database(path, 6)
                        o = MarkerObservation(owner, records)
                        with patch('sqlite3.connect', o.connect):
                            with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)) as db:
                                db.execute('BEGIN').close()
                                non_target = db.execute('SELECT 37')
                                self.assertEqual(non_target.fetchone(), (37,))
                                self.assertIsNone(non_target.fetchone())
                                non_target.close()
                                target = db.execute(sql)
                                expected = actual if records is None else records
                                self.assertEqual(list(iter(target.fetchone, None)), expected)
                                self.assertEqual(target.eof, 1)
                                target.close()
                        self.assertEqual(o.hits[owner], 1)
                        self.assertEqual(sum(o.hits.values()), 1)
                        self.assertEqual(o.non_target, 2)
                        self.assertTrue(o.connections[0].closed)
                        self.assertTrue(all(c.closed == 1 for c in o.cursors))

    def test_read_cancel_and_close_injections_fire_only_on_target_values(self):
        for action, error in (('read', sqlite3.OperationalError), ('cancel', KeyboardInterrupt)):
            with self.subTest(action=action), tempfile.TemporaryDirectory() as td:
                path = Path(td) / 'public.sqlite'
                create_public_core_database(path, 6)
                o = MarkerObservation('sqlite_physical', [(0,), (0,)], action,
                                      close_failure=True)
                with patch('sqlite3.connect', o.connect):
                    with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)) as db:
                        unaffected = db.execute('SELECT 37')
                        self.assertEqual(unaffected.fetchone(), (37,))
                        unaffected.close()
                        target = db.execute(PHYSICAL)
                        self.assertEqual(target.fetchone(), (0,))
                        with self.assertRaises(error):
                            target.fetchone()
                        with self.assertRaises(sqlite3.OperationalError):
                            target.close()
                self.assertEqual((o.fired, o.close_fired), (1, 1))
                self.assertEqual(o.non_target, 1)


    def test_deadline_and_final_cleanup_instrumentation_are_targeted(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'public.sqlite'
            create_public_core_database(path, 6)
            o = MarkerObservation('sqlite_physical', [(0,), (0,)], 'deadline',
                                  final_failure=True, late_deadline=True)
            with patch('sqlite3.connect', o.connect):
                db = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)
                other = db.execute('SELECT 37')
                self.assertEqual(other.fetchone(), (37,))
                other.close()
                self.assertEqual((o.now, o.fired), (0, 0))
                target = db.execute(PHYSICAL)
                self.assertEqual(target.fetchone(), (0,))
                self.assertEqual(o.now, 0)
                self.assertEqual(target.fetchone(), (0,))
                self.assertEqual((o.now, o.fired), (1000, 1))
                self.assertIsNone(target.fetchone())
                target.close()
                with self.assertRaises(sqlite3.OperationalError):
                    db.close()
            self.assertEqual(o.final_fired, 1)
            self.assertTrue(o.connections[0].closed)
            self.assertEqual((o.hits['sqlite_physical'], o.non_target), (1, 1))
            self.assertTrue(all(c.closed == 1 for c in o.cursors))


class IntegrityD3bSQLite(CountedAssertions):
    def scan(self, path, observation, cap=None):
        with ExitStack() as stack:
            stack.enter_context(patch('sqlite3.connect', observation.connect))
            stack.enter_context(patch(MODULE + 'monotonic', lambda: observation.now))
            if cap is not None:
                stack.enter_context(patch(MODULE + 'MAX_ROWS', cap))
            return SQLiteIntegrityScanner().scan(str(path))

    def public(self, td, version=6):
        path = Path(td) / 'public.sqlite'
        # Genuine historical DDL; A qualifies native physical/FK health for
        # each version. Empty retained/graph/evidence is not a populated-content
        # certificate or a private writer fixture.
        create_public_core_database(path, version)
        return path

    def assert_access_interrupted(self, result, stop, code):
        self.assertEqual(result.stop_reason, stop)
        self.assertEqual(state(result, 'resource_access'), ('interrupted', 0, 'lower_bound'))
        self.assertIn((code, 'operational', 1, 'lower_bound'), findings(result, 'resource_access'))
        self.assertFalse(result.implemented_scope_complete)
        self.assertNotIn('PRIVATE', repr(result))

    def test_genuine_supported_healthy_physical_one_and_foreign_keys_zero(self):
        for version in range(6, 11):
            with self.subTest(version=version), tempfile.TemporaryDirectory() as td:
                path = self.public(td, version)
                o = MarkerObservation()
                result = self.scan(path, o)
                self.assertEqual(state(result, 'sqlite_physical'), ('completed', 1, 'exact'))
                self.assertEqual(state(result, 'sqlite_foreign_keys'), ('completed', 0, 'exact'))
                self.assertEqual(result.stop_reason, 'completed')
                self.assertEqual(findings(result, 'sqlite_physical'), [])
                self.assertEqual(findings(result, 'sqlite_foreign_keys'), [])
                self.assertEqual(len(o.connections), 1)
                self.assertIn('BEGIN', o.trace)
                self.assertTrue(all(c.closed == 1 for c in o.cursors))
                self.assertTrue(all(c.eof >= 1 for c in o.cursors if c.owner))

    def test_genuine_public_orphan_is_one_fk_record_owned_by_foreign_keys(self):
        with tempfile.TemporaryDirectory() as td:
            path = self.public(td)
            with closing(sqlite3.connect(path)) as db:
                db.execute('PRAGMA foreign_keys=OFF')
                db.execute('INSERT INTO track_audio VALUES(?,?,?,?,?)',
                           ('sha256:' + '9' * 64, 1.0, 'mutagen', 'eligible', ''))
                db.commit()
            o = MarkerObservation()
            result = self.scan(path, o)
            self.assertEqual(state(result, 'sqlite_physical'), ('completed', 1, 'exact'))
            self.assertEqual(state(result, 'sqlite_foreign_keys'), ('completed', 1, 'exact'))
            self.assertEqual(findings(result, 'sqlite_foreign_keys'),
                             [('sqlite_foreign_key_invalid', 'corruption', 1, 'exact')])
            self.assertEqual(result.stop_reason, 'completed')
            self.assertNotIn('track_audio', repr(result))
            self.assertNotIn('sha256:' + '9' * 64, repr(result))
            self.assertEqual(len(o.connections), 1)
            self.assertTrue(all(c.eof == 1 for c in o.cursors if c.owner))
            self.assertTrue(all(c.closed == 1 for c in o.cursors))

    def test_physical_one_to_ninety_nine_non_ok_records_require_eof_and_cleanup(self):
        for count in (1, 99):
            with self.subTest(count=count), tempfile.TemporaryDirectory() as td:
                o = MarkerObservation('sqlite_physical', [(0,)] * count)
                result = self.scan(self.public(td), o)
                self.assertEqual(state(result, 'sqlite_physical'), ('completed', count, 'exact'))
                self.assertEqual(findings(result, 'sqlite_physical'),
                                 [('sqlite_integrity_invalid', 'corruption', count, 'exact')])
                self.assertTrue(all(c.eof == 1 for c in o.cursors if c.owner == o.target))
                self.assertEqual(result.stop_reason, 'completed')

    def test_physical_one_hundred_is_cutoff_even_if_eof_would_follow(self):
        with tempfile.TemporaryDirectory() as td:
            o = MarkerObservation('sqlite_physical', [(0,)] * 100)
            result = self.scan(self.public(td), o)
            self.assertEqual(state(result, 'sqlite_physical'), ('interrupted', 100, 'lower_bound'))
            self.assertEqual(findings(result, 'sqlite_physical'),
                             [('sqlite_integrity_invalid', 'corruption', 100, 'lower_bound')])
            self.assert_access_interrupted(result, 'physical_limit', 'physical_limit_reached')
            values = [c for c in o.cursors if c.owner == o.target and not c.preflight]
            self.assertEqual(len(values), 1)
            self.assertEqual((values[0].fetched, values[0].eof, values[0].closed), (100, 0, 1))
            self.assertEqual(state(result, 'sqlite_foreign_keys'), ('blocked', None, 'unavailable'))
            self.assertEqual(o.hits['sqlite_foreign_keys'], 0)

    def test_foreign_key_records_have_no_physical_cutoff(self):
        with tempfile.TemporaryDirectory() as td:
            # Marker1 means violation here, not physical ok. Deliberately102.
            o = MarkerObservation('sqlite_foreign_keys', [(1,)] * 102)
            result = self.scan(self.public(td), o)
            self.assertEqual(state(result, 'sqlite_foreign_keys'), ('completed', 102, 'exact'))
            self.assertEqual(findings(result, 'sqlite_foreign_keys'),
                             [('sqlite_foreign_key_invalid', 'corruption', 102, 'exact')])
            self.assertEqual(state(result, 'sqlite_physical'), ('completed', 1, 'exact'))
            self.assertEqual(result.stop_reason, 'completed')
            self.assertTrue(all(c.eof == 1 for c in o.cursors if c.owner == o.target))

    def test_malformed_physical_marker_stream_is_operational_not_corruption(self):
        for records in ([], [(1,), (1,)], [(0,), (1,)], [(1,), (0,)], [('ok',)], [(True,)], [(None,)], [(0, 0)]):
            with self.subTest(records=records), tempfile.TemporaryDirectory() as td:
                o = MarkerObservation('sqlite_physical', records)
                result = self.scan(self.public(td), o)
                self.assert_access_interrupted(result, 'read_error', 'read_failed')
                self.assertEqual(state(result, 'sqlite_physical')[0::2], ('interrupted', 'lower_bound'))
                self.assertEqual(state(result, 'sqlite_foreign_keys'), ('blocked', None, 'unavailable'))
                self.assertFalse(result.implemented_scope_complete)

    def test_read_deadline_close_and_cancel_keep_prefix_and_block_later_work(self):
        for owner in ('sqlite_physical', 'sqlite_foreign_keys'):
            marker = 0 if owner == 'sqlite_physical' else 1
            corruption = 'sqlite_integrity_invalid' if marker == 0 else 'sqlite_foreign_key_invalid'
            for mode in ('read', 'deadline', 'close', 'cancel'):
                with self.subTest(owner=owner, mode=mode), tempfile.TemporaryDirectory() as td:
                    # Close failure after EOF retains both records; others stop
                    # during second value so only one semantic record admitted.
                    o = MarkerObservation(owner, [(marker,)] * 2,
                                          None if mode == 'close' else mode,
                                          close_failure=mode in ('close', 'cancel'))
                    result = self.scan(self.public(td), o)
                    count = 2 if mode == 'close' else 1
                    self.assertEqual(state(result, owner), ('interrupted', count, 'lower_bound'))
                    self.assertEqual(findings(result, owner), [(corruption, 'corruption', count, 'lower_bound')])
                    stop, code = {'read': ('read_error', 'read_failed'),
                                  'deadline': ('deadline', 'deadline_exceeded'),
                                  'close': ('cleanup_error', 'cleanup_failed'),
                                  'cancel': ('cancelled', 'cancelled')}[mode]
                    self.assert_access_interrupted(result, stop, code)
                    if mode == 'cancel':
                        self.assertIn(('cleanup_failed', 'operational', 1, 'lower_bound'),
                                      findings(result, 'resource_access'))
                    if owner == 'sqlite_physical':
                        self.assertEqual(state(result, 'sqlite_foreign_keys'), ('blocked', None, 'unavailable'))
                        self.assertEqual(o.hits['sqlite_foreign_keys'], 0)
                    else:
                        self.assertEqual(state(result, 'sqlite_physical'), ('completed', 1, 'exact'))
                    self.assertEqual(o.fired, int(mode != 'close'))
                    self.assertTrue(all(c.closed == 1 for c in o.cursors))

    def test_fk_read_error_before_first_record_never_invents_violation(self):
        with tempfile.TemporaryDirectory() as td:
            o = MarkerObservation('sqlite_foreign_keys', [(1,)], 'read', after=0)
            result = self.scan(self.public(td), o)
            self.assertEqual(state(result, 'sqlite_foreign_keys'), ('interrupted', 0, 'lower_bound'))
            self.assertEqual(findings(result, 'sqlite_foreign_keys'), [])
            self.assertEqual(state(result, 'sqlite_physical'), ('completed', 1, 'exact'))
            self.assert_access_interrupted(result, 'read_error', 'read_failed')
            self.assertEqual(o.fired, 1)

    def test_shared_row_meter_does_not_reset_at_either_sqlite_phase(self):
        for owner in ('sqlite_physical', 'sqlite_foreign_keys'):
            with self.subTest(owner=owner), tempfile.TemporaryDirectory() as td:
                path = self.public(td)
                marker = 0 if owner == 'sqlite_physical' else 1
                calibration = MarkerObservation(owner, [(marker,)] * 2)
                baseline = self.scan(path, calibration)
                self.assertEqual(state(baseline, owner), ('completed', 2, 'exact'))
                # Exhaust the already-used global meter at target entry. This
                # does not assume whether this bounded numeric phase uses a
                # preflight/value pair or a specialized single cursor.
                cap = calibration.starts[owner]
                self.assertGreater(cap, 0)
                o = MarkerObservation(owner, [(marker,)] * 2)
                result = self.scan(path, o, cap)
                self.assertEqual(state(result, owner), ('interrupted', 0, 'lower_bound'))
                self.assertEqual(findings(result, owner), [])
                self.assert_access_interrupted(result, 'row_limit', 'row_limit_reached')
                if owner == 'sqlite_foreign_keys':
                    self.assertEqual(state(result, 'sqlite_physical'), ('completed', 1, 'exact'))
                else:
                    self.assertEqual(state(result, 'sqlite_foreign_keys'), ('blocked', None, 'unavailable'))

    def test_final_cleanup_and_late_deadline_keep_drained_phases_exact_but_prevent_completion(self):
        for late in (False, True):
            with self.subTest(late_deadline=late), tempfile.TemporaryDirectory() as td:
                o = MarkerObservation(final_failure=not late, late_deadline=late)
                result = self.scan(self.public(td), o)
                self.assertEqual(state(result, 'sqlite_physical'), ('completed', 1, 'exact'))
                self.assertEqual(state(result, 'sqlite_foreign_keys'), ('completed', 0, 'exact'))
                self.assert_access_interrupted(result, 'deadline' if late else 'cleanup_error',
                                               'deadline_exceeded' if late else 'cleanup_failed')
                self.assertTrue(o.connections[0].closed)
                self.assertEqual(o.final_fired, int(not late))
