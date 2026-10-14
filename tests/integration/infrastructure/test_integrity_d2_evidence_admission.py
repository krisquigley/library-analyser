"""C packet: independent admission controls and prospective scanner RED.

Fixed SQL scratch probes qualify only this test algorithm, not a future scanner.
Delivery/size transformations are proxy-only, not physically persisted defects.
"""
from contextlib import closing
from pathlib import Path
import codecs
import hashlib
import json
import sqlite3
import tempfile
import unittest
import weakref
from unittest.mock import patch

from music_analyzer.infrastructure.persistence.integrity import SQLiteIntegrityScanner, Delivery, AdmissionStop
from time import monotonic
from tests.integration.infrastructure.integrity_d2_evidence_public_fixture import (
    create_public_evidence_database, payload, canonical, fingerprint, store_payload,
    change, OLD_RUNS, CURRENT_RUNS,
)

DOMAIN = 16 << 20
OWNERS = ('current_evidence', 'historical_evidence')
SLICE_SQL = ('SELECT substr(CAST(evidence_json AS BLOB),?,4096) '
             'FROM graph_feature_evidence WHERE track_id=? AND run_id=?')


def evidence_sql(sql):
    normalized = ' '.join(sql.lower().split())
    return normalized.startswith('select ') and ' from graph_feature_evidence' in normalized


def canonical_target_failure(value, *args, **kwargs):
    if (isinstance(value, dict) and value.get('run_id') == OLD_RUNS[0]
            and kwargs.get('sort_keys') and kwargs.get('ensure_ascii') is False):
        raise RecursionError('PRIVATE canonical depth')
    return ORIGINAL_DUMPS(value, *args, **kwargs)


ORIGINAL_DUMPS = json.dumps


def create_encoded(path, encoding='UTF-8', version=10):
    with closing(sqlite3.connect(path)) as db:
        db.execute("PRAGMA encoding='" + encoding + "'")
        # Encoding is fixed by the first schema object, not a later PRAGMA.
        db.execute('CREATE TABLE encoding_seed(value)')
        db.execute('DROP TABLE encoding_seed')
        db.commit()
    return create_public_evidence_database(path, version)


def count_slices(db, track, run, codec, *, blob=False, saturate=None):
    """Probe approved byte SQL with bounded incremental state, no value query."""
    size = db.execute('SELECT length(CAST(evidence_json AS BLOB)) FROM graph_feature_evidence WHERE track_id=? AND run_id=?', (track, run)).fetchone()[0]
    decoder = codecs.getincrementaldecoder(codec)(errors='surrogatepass' if blob else 'strict')
    total = delivered = 0
    for offset in range(1, size + 1, 4096):
        with closing(db.execute(SLICE_SQL, (offset, track, run))) as cursor:
            fragment = cursor.fetchone()[0]
        if not isinstance(fragment, bytes) or len(fragment) > 4096:
            raise AssertionError('Unbounded or missing fixed SQL fragment')
        delivered += len(fragment)
        decoded = decoder.decode(fragment, final=delivered == size)
        total += len(decoded.encode('utf-8'))
        if saturate is not None and total > saturate:
            return total, delivered, size
    return total, delivered, size


def sized_payload(track, run, size, character='x'):
    value = payload(track, run)
    base = len(canonical(value).encode('utf-8'))
    width = len(character.encode('utf-8'))
    count, rest = divmod(size - base, width)
    value['features']['bpm']['uncertainty'] = character * count + 'x' * rest
    text = canonical(value)
    if len(text.encode('utf-8')) != size:
        raise AssertionError('Independent boundary fixture size mismatch')
    return value, text


def selected(scan, owner):
    return next(c for c in scan.checks if c.check_id == owner)


def findings(scan):
    return [(f.check_id, f.code, f.count, f.count_precision) for f in scan.findings if f.check_id in OWNERS]


class Observation:
    """Match real evidence columns; direct controls must prove faults fire.

    Never infer physical corruption from this wrapper. Reject bulk reads only on
    evidence; unrelated fixed schema inventory controls may legitimately batch.
    """
    def __init__(self, target=OLD_RUNS[0], fault=None):
        self.real_connect = sqlite3.connect
        self.target, self.fault = target, fault
        self.pending_fault = False
        self.matched = self.fired = 0
        self.value_runs = []
        self.cursors = self.closed_cursors = self.closed_connections = 0
        self.handler_cleared = False
        self.after_value = None
        self.before_payload_request = None
        self.on_fault = self.on_late_close = self.on_deadline = None

    def connect(self, *args, **kwargs):
        return Connection(self.real_connect(*args, **kwargs), self)


class Cursor:
    def __init__(self, cursor, observation, evidence, sql, params=()):
        self.raw, self.observation, self.evidence, self.sql = cursor, observation, evidence, sql
        self.params = params
        self.pending_duplicate = None
        self.seen_target = False
        self.closed = False
        observation.cursors += 1

    def fetchone(self):
        obs = self.observation
        if self.pending_duplicate is not None:
            row, self.pending_duplicate = self.pending_duplicate, None
            obs.matched += 1
            obs.fired += 1
            obs.value_runs.append(obs.target)
            return row
        if (self.evidence and obs.before_payload_request
                and self.raw.description and 'evidence_json' in [c[0].lower() for c in self.raw.description]):
            obs.before_payload_request()
        if (self.evidence and obs.pending_fault and obs.fault in ('read', 'cancel', 'codec', 'length_read', 'read_cleanup', 'read_cancel_cleanup')
                and (obs.fault != 'length_read' or 'length(' in self.sql.lower() or 'typeof(' in self.sql.lower())):
            obs.fired += 1
            if obs.on_fault:
                obs.on_fault()
            if obs.fault == 'cancel':
                raise KeyboardInterrupt
            if obs.fault == 'codec':
                raise UnicodeError('PRIVATE delivery codec')
            raise sqlite3.OperationalError('PRIVATE SQL cursor fault')
        if self.evidence and obs.pending_fault and obs.fault == 'deadline' and obs.on_deadline:
            obs.fired += 1
            obs.on_deadline()
        row = self.raw.fetchone()
        if row is not None and self.evidence:
            columns = [item[0].lower() for item in self.raw.description]
            if (('run_id' in columns and row[columns.index('run_id')] == obs.target)
                    or ('run_id' not in columns and obs.target in self.params)):
                obs.matched += 1
                # Fault on the next actual evidence cursor fetch, even when
                # the singleton value cursor was closed before that fetch.
                # The corrupt full payload must be delivered first.
                if 'evidence_json' in columns:
                    # Genuine PK plus pinned snapshot cannot persist missing or
                    # duplicate delivered rows. These are cursor-only proxies,
                    # AFTER the independent envelope has admitted this identity.
                    if obs.fault == 'missing':
                        obs.fired += 1
                        return None
                    if obs.fault == 'duplicate':
                        self.pending_duplicate = row
                    self.seen_target = True
                    obs.pending_fault = True
                    obs.value_runs.append(obs.target)
                    if obs.fault in ('scalar', 'null'):
                        row = list(row)
                        row[columns.index('evidence_json')] = 7 if obs.fault == 'scalar' else None
                        row = tuple(row)
                        obs.fired += 1
                    if obs.after_value:
                        callback, obs.after_value = obs.after_value, None
                        callback()
                    if obs.fault == 'identity' and 'run_id' in columns:
                        row = list(row); row[columns.index('run_id')] = 'unexpected-proxy'; row = tuple(row)
                        obs.fired += 1
            if (obs.fault == 'size' and 'run_id' in columns
                    and row[columns.index('run_id')] == obs.target
                    and any('length(' in col for col in columns)):
                row = tuple(-5 if 'length(' in col else val for col, val in zip(columns, row))
                obs.fired += 1
        return row

    def __iter__(self):
        while (row := self.fetchone()) is not None:
            yield row

    def fetchall(self):
        if self.evidence:
            raise AssertionError('Evidence bulk materialization prohibited')
        return self.raw.fetchall()

    def fetchmany(self, *args):
        if self.evidence:
            raise AssertionError('Evidence bulk materialization prohibited')
        return self.raw.fetchmany(*args)

    def close(self):
        self.pending_duplicate = None
        if not self.closed:
            self.closed = True
            self.observation.closed_cursors += 1
        self.raw.close()
        if self.evidence and self.observation.fired and self.observation.on_late_close:
            self.observation.on_late_close()
        if self.evidence and self.observation.fired and self.observation.fault in ('read_cleanup', 'read_cancel_cleanup'):
            if self.observation.fault == 'read_cancel_cleanup':
                raise KeyboardInterrupt
            raise sqlite3.OperationalError('PRIVATE combined cleanup')
        if self.evidence and self.seen_target and self.observation.fault == 'cleanup':
            self.observation.fired += 1
            raise sqlite3.OperationalError('PRIVATE cleanup')

    def __getattr__(self, name):
        return getattr(self.raw, name)


class Connection:
    def __init__(self, raw, observation):
        self.raw, self.observation = raw, observation

    def execute(self, sql, *args):
        evidence = 'graph_feature_evidence' in sql.lower() and sql.lstrip().upper().startswith('SELECT')
        return Cursor(self.raw.execute(sql, *args), self.observation, evidence, sql, args[0] if args else ())

    def set_progress_handler(self, callback, n):
        if callback is None:
            self.observation.handler_cleared = True
        return self.raw.set_progress_handler(callback, n)

    def close(self):
        self.observation.closed_connections += 1
        self.raw.close()

    def __getattr__(self, name):
        return getattr(self.raw, name)


class AdmissionCase(unittest.TestCase):
    def public(self, encoding='UTF-8', version=10):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        path = Path(temporary.name) / 'public.sqlite'
        return path, create_encoded(path, encoding, version)

    def scan(self, path, observation=None):
        if observation is None:
            return SQLiteIntegrityScanner().scan(str(path))
        with patch('sqlite3.connect', observation.connect):
            return SQLiteIntegrityScanner().scan(str(path))

    def assert_complete(self, scan):
        for owner in OWNERS:
            c = selected(scan, owner)
            self.assertEqual((c.state, c.count, c.count_precision), ('completed', 2, 'exact'))
        self.assertTrue(scan.implemented_scope_complete)


class IntegrityD2EvidenceAdmissionControls(AdmissionCase):
    def test_real_utf16_nul_tail_and_split_surrogates(self):
        for encoding, codec in (('UTF-16le', 'utf-16-le'), ('UTF-16be', 'utf-16-be')):
            with self.subTest(encoding=encoding):
                path, ids = self.public(encoding)
                # High surrogate occupies bytes4094..4095; its low half starts
                # the next slice. Embedded NUL hides the following TEXT tail
                # from SQLite length(TEXT), but never the BLOB byte drainage.
                text = 'a' * 2047 + '\U0001f600' + '\0' + '尾' * 4097
                change(path, 'UPDATE graph_feature_evidence SET evidence_json=? WHERE run_id=?', (text, OLD_RUNS[0]))
                with closing(sqlite3.connect(path)) as db:
                    self.assertEqual(db.execute('PRAGMA encoding').fetchone()[0].lower(), encoding.lower())
                    self.assertEqual(db.execute('SELECT length(evidence_json) FROM graph_feature_evidence WHERE run_id=?', (OLD_RUNS[0],)).fetchone()[0], 2048)
                    total, delivered, storage = count_slices(db, ids[0], OLD_RUNS[0], codec)
                    self.assertEqual(total, len(text.encode('utf-8')))
                    self.assertEqual(delivered, storage)
                    self.assertGreater(storage, 8192)
                    self.assertEqual(db.execute('PRAGMA integrity_check').fetchone(), ('ok',))
                    self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(), [])

    def test_text_bom_is_preserved_by_recognized_codec(self):
        for encoding, codec in (('UTF-16le', 'utf-16-le'), ('UTF-16be', 'utf-16-be')):
            with self.subTest(encoding=encoding):
                path, ids = self.public(encoding)
                text = '\ufeff{}'
                change(path, 'UPDATE graph_feature_evidence SET evidence_json=? WHERE run_id=?', (text, OLD_RUNS[0]))
                with closing(sqlite3.connect(path)) as db:
                    total, drained, storage = count_slices(db, ids[0], OLD_RUNS[0], codec)
                    self.assertEqual(total, 5)
                    self.assertEqual((drained, storage), (6, 6))
                with self.assertRaises(json.JSONDecodeError):
                    json.loads(text)

    def test_real_blob_odd_split_bom_and_surrogatepass_controls(self):
        path, ids = self.public()
        for codec in ('utf-8-sig', 'utf-16', 'utf-32'):
            with self.subTest(codec=codec):
                text = '"' + 'a' * 2046 + '\U0001f600' + '尾' * 3000 + '"'
                raw = text.encode(codec)
                change(path, 'UPDATE graph_feature_evidence SET evidence_json=? WHERE run_id=?', (raw, OLD_RUNS[0]))
                with closing(sqlite3.connect(path)) as db:
                    total, delivered, storage = count_slices(db, ids[0], OLD_RUNS[0], codec, blob=True)
                    self.assertEqual(total, len(text.encode('utf-8')))
                    self.assertEqual((delivered, storage), (len(raw), len(raw)))
                self.assertEqual(json.loads(raw), json.loads(text))
        decoder = codecs.getincrementaldecoder('utf-16-le')('strict')
        raw = 'a\U0001f600尾'.encode('utf-16-le')
        self.assertEqual(''.join(decoder.decode(raw[i:i+1], final=i == len(raw)-1) for i in range(len(raw))), 'a\U0001f600尾')
        with self.assertRaises(UnicodeDecodeError):
            codecs.getincrementaldecoder('utf-16-le')('strict').decode(b'a', final=True)
        self.assertEqual(json.loads(b'"\xed\xa0\x80"'), '\ud800')
        with self.assertRaises(UnicodeEncodeError):
            json.loads(b'"\xed\xa0\x80"').encode('utf-8')

    def test_wrappers_direct_faults_match_fire_and_close(self):
        path, _ = self.public()
        change(path, 'UPDATE graph_feature_evidence SET evidence_json=? WHERE run_id=?', ('{', OLD_RUNS[0]))
        sql = 'SELECT run_id,evidence_json FROM graph_feature_evidence WHERE run_id=?'
        for fault in (None, 'read', 'cancel', 'codec', 'identity', 'cleanup'):
            with self.subTest(fault=fault):
                obs = Observation(fault=fault)
                db = obs.connect(path); cursor = db.execute(sql, (OLD_RUNS[0],))
                row = cursor.fetchone()
                self.assertEqual(row[1], '{')
                self.assertEqual(row[0], 'unexpected-proxy' if fault == 'identity' else OLD_RUNS[0])
                if fault in ('read', 'cancel', 'codec'):
                    with self.assertRaises({'read': sqlite3.Error, 'cancel': KeyboardInterrupt, 'codec': UnicodeError}[fault]):
                        cursor.fetchone()
                else:
                    self.assertIsNone(cursor.fetchone())
                if fault == 'cleanup':
                    with self.assertRaises(sqlite3.Error):
                        cursor.close()
                else:
                    cursor.close()
                db.close()
                self.assertEqual(obs.matched, 1)
                self.assertEqual(obs.fired, int(fault is not None))
                self.assertEqual((obs.cursors, obs.closed_cursors, obs.closed_connections), (1, 1, 1))
        obs = Observation(fault='size')
        with closing(obs.connect(path)) as db:
            with closing(db.execute('SELECT run_id,length(CAST(evidence_json AS BLOB)) FROM graph_feature_evidence WHERE run_id=?', (OLD_RUNS[0],))) as cursor:
                self.assertEqual(cursor.fetchone(), (OLD_RUNS[0], -5))
        self.assertEqual(obs.fired, 1)

    def test_cross_cursor_length_fault_and_raw_scalar_proxies_fire(self):
        path, _ = self.public()
        obs = Observation(fault='length_read')
        with closing(obs.connect(path)) as db:
            with closing(db.execute('SELECT run_id,evidence_json FROM graph_feature_evidence WHERE run_id=?', (OLD_RUNS[0],))) as cursor:
                self.assertIsInstance(cursor.fetchone()[1], str)
            with closing(db.execute('SELECT run_id,length(CAST(evidence_json AS BLOB)) FROM graph_feature_evidence WHERE run_id=?', (OLD_RUNS[1],))) as cursor:
                with self.assertRaises(sqlite3.Error):
                    cursor.fetchone()
        self.assertEqual((obs.matched, obs.fired), (1, 1))
        for fault, expected in (('scalar', 7), ('null', None)):
            with self.subTest(fault=fault):
                obs = Observation(fault=fault)
                with closing(obs.connect(path)) as db:
                    with closing(db.execute('SELECT run_id,evidence_json FROM graph_feature_evidence WHERE run_id=?', (OLD_RUNS[0],))) as cursor:
                        self.assertEqual(cursor.fetchone(), (OLD_RUNS[0], expected))
                self.assertEqual((obs.matched, obs.fired), (1, 1))

    def test_missing_and_duplicate_delivery_proxies_healthy_and_firing(self):
        path, _ = self.public()
        sql = 'SELECT run_id,evidence_json FROM graph_feature_evidence WHERE run_id=?'
        with closing(sqlite3.connect(path)) as db:
            original = db.execute(sql, (OLD_RUNS[0],)).fetchone()
            self.assertIsNotNone(original)
            self.assertIsInstance(original[1], str)
        for fault, expected, matched, fired in (
            (None, [original], 1, 0),
            ('missing', [], 1, 1),
            ('duplicate', [original, original], 2, 1),
        ):
            with self.subTest(fault=fault):
                obs = Observation(fault=fault)
                with closing(obs.connect(path)) as db:
                    # The envelope is genuinely delivered unchanged FIRST;
                    # faults match only whole-value column, never preflight.
                    with closing(db.execute('SELECT run_id,length(CAST(evidence_json AS BLOB)) FROM graph_feature_evidence WHERE run_id=?', (OLD_RUNS[0],))) as cursor:
                        envelope = cursor.fetchone()
                        self.assertEqual(envelope[0], OLD_RUNS[0])
                        self.assertGreater(envelope[1], 0)
                    self.assertEqual(obs.fired, 0)
                    with closing(db.execute(sql, (OLD_RUNS[0],))) as cursor:
                        self.assertEqual(list(cursor), expected)
                # matched includes the independent admitted envelope.
                self.assertEqual((obs.matched, obs.fired), (matched + 1, fired))
                self.assertEqual(obs.cursors, obs.closed_cursors)
                self.assertEqual(obs.closed_connections, 1)
        with closing(sqlite3.connect(path)) as db:
            self.assertEqual(db.execute(sql, (OLD_RUNS[0],)).fetchone(), original)
            self.assertEqual(db.execute('SELECT count(*) FROM graph_feature_evidence').fetchone(), (4,))
            self.assertEqual(db.execute('PRAGMA integrity_check').fetchone(), ('ok',))
            self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(), [])
        # No persisted physical missing/duplicate, DDL/index drift or read error.

    def test_combined_read_cleanup_and_cancel_selfcontrols(self):
        path, _ = self.public()
        for fault, error in (('read_cleanup', sqlite3.Error), ('read_cancel_cleanup', KeyboardInterrupt)):
            with self.subTest(fault=fault):
                obs = Observation(fault=fault)
                with closing(obs.connect(path)) as db:
                    cursor = db.execute('SELECT run_id,evidence_json FROM graph_feature_evidence WHERE run_id=?', (OLD_RUNS[0],))
                    cursor.fetchone()
                    with self.assertRaises(sqlite3.Error):
                        cursor.fetchone()
                    with self.assertRaises(error):
                        cursor.close()
                self.assertEqual(obs.fired, 1)
                self.assertEqual(obs.cursors, obs.closed_cursors)
                self.assertEqual(obs.closed_connections, 1)

    def test_fault_clock_and_late_close_hooks_selfcontrol(self):
        path, _ = self.public()
        for fault in ('read', 'deadline'):
            with self.subTest(fault=fault):
                obs = Observation(fault=fault)
                clock = [0]
                obs.on_fault = lambda: clock.__setitem__(0, 1)
                obs.on_deadline = lambda: clock.__setitem__(0, 121)
                obs.on_late_close = lambda: clock.__setitem__(0, 121)
                with closing(obs.connect(path)) as db:
                    cursor = db.execute('SELECT run_id,evidence_json FROM graph_feature_evidence WHERE run_id=?', (OLD_RUNS[0],))
                    cursor.fetchone()
                    self.assertEqual(clock[0], 0)
                    if fault == 'read':
                        with self.assertRaises(sqlite3.Error):
                            cursor.fetchone()
                        self.assertEqual(clock[0], 1)
                    else:
                        self.assertIsNone(cursor.fetchone())
                        self.assertEqual(clock[0], 121)
                    cursor.close()
                    self.assertEqual(clock[0], 121)
                self.assertEqual(obs.fired, 1)
                self.assertEqual(obs.cursors, obs.closed_cursors)

    def test_payload_request_lifetime_observer_selfcontrol(self):
        class Tracked(dict):
            pass
        value = Tracked({'public': 1})
        ref = weakref.ref(value)
        path, _ = self.public()
        obs = Observation()
        def released():
            self.assertIsNone(ref(), 'Previous decoded record retained at next payload request')
        obs.before_payload_request = released
        with closing(obs.connect(path)) as db:
            with closing(db.execute('SELECT run_id,evidence_json FROM graph_feature_evidence WHERE run_id=?', (OLD_RUNS[0],))) as cursor:
                with self.assertRaises(AssertionError):
                    cursor.fetchone()
                del value
                self.assertIsInstance(cursor.fetchone()[1], str)
        self.assertIsNone(ref())

    def test_group_capacity_selfcontrol_proxy_not_physical_evidence(self):
        # The finite current evidence taxonomy cannot create101 groups. This
        # direct resource seam is a capacity proxy, not invented row corruption.
        with closing(sqlite3.connect(':memory:')) as db:
            delivery = Delivery(db, monotonic() + 2)
            for i in range(100):
                delivery.claim_group('capacity-proxy', str(i))
            delivery.claim_group('capacity-proxy', '0')
            self.assertEqual(len(delivery.group_keys), 100)
            with self.assertRaises(AdmissionStop) as caught:
                delivery.claim_group('capacity-proxy', '100')
            self.assertEqual(caught.exception.reason, 'finding_limit')
            self.assertTrue(delivery.findings_truncated)

    def test_canonical_recursion_proxy_fires_only_canonical_operation(self):
        target = {'run_id': OLD_RUNS[0]}
        other = {'run_id': CURRENT_RUNS[0]}
        self.assertEqual(canonical_target_failure(target), ORIGINAL_DUMPS(target))
        self.assertEqual(canonical_target_failure(other, sort_keys=True, ensure_ascii=False),
                         ORIGINAL_DUMPS(other, sort_keys=True, ensure_ascii=False))
        with self.assertRaises(RecursionError):
            canonical_target_failure(target, sort_keys=True, ensure_ascii=False)

    def test_evidence_budget_boundary_excludes_schema_and_matches_delivery(self):
        self.assertFalse(evidence_sql("SELECT name FROM pragma_table_info('graph_feature_evidence') ORDER BY cid"))
        self.assertFalse(evidence_sql("SELECT length(CAST(name AS BLOB)) FROM (SELECT name FROM pragma_table_info('graph_feature_evidence'))"))
        self.assertTrue(evidence_sql('SELECT track_id,run_id FROM graph_feature_evidence WHERE is_current=1'))
        self.assertTrue(evidence_sql('SELECT length(CAST(track_id AS BLOB)) FROM (SELECT track_id FROM graph_feature_evidence WHERE is_current=1)'))

    def test_real_parser_recursive_input_control(self):
        raw = ('[' * 10000 + '0' + ']' * 10000).encode()
        with self.assertRaises(RecursionError):
            json.loads(raw)

    def test_delivery_reduced_budget_selfcontrols_are_shared_and_inclusive(self):
        # Existing Delivery controls are NOT prospective evidence-scanner RED.
        with closing(sqlite3.connect(':memory:')) as db:
            for budget, limit, text, reason in (
                ('MAX_VALUE_BYTES', 8, 'x' * 8, None),
                ('MAX_VALUE_BYTES', 8, 'x' * 9, 'value_limit'),
                ('MAX_UTF8_BYTES', 8, 'x' * 8, None),
                ('MAX_UTF8_BYTES', 8, 'x' * 9, 'utf8_limit'),
                ('MAX_ROWS', 1, 'x', 'row_limit'),
            ):
                with self.subTest(budget=budget, text=len(text)):
                    delivery = Delivery(db, monotonic() + 2)
                    with patch('music_analyzer.infrastructure.persistence.integrity.' + budget, limit):
                        rows = delivery.rows('SELECT ? AS value', ('value',), (text,))
                        try:
                            if reason is None:
                                self.assertEqual(list(rows), [(text,)])
                            else:
                                with self.assertRaises(AdmissionStop) as caught:
                                    list(rows)
                                self.assertEqual(caught.exception.reason, reason)
                        finally:
                            rows.close()
            delivery = Delivery(db, monotonic() + 2)
            with patch('music_analyzer.infrastructure.persistence.integrity.MAX_UTF8_BYTES', 8):
                self.assertEqual(list(delivery.rows("SELECT '12345' AS value", ('value',))), [('12345',)])
                with self.assertRaises(AdmissionStop) as caught:
                    list(delivery.rows("SELECT '1234' AS value", ('value',)))
                self.assertEqual(caught.exception.reason, 'utf8_limit')
                self.assertEqual(delivery.utf8_bytes, 5)

    def test_healthy_scanner_wrapper_and_two_connection_snapshot_barrier(self):
        path, _ = self.public()
        obs = Observation()
        scan = self.scan(path, obs)
        self.assertFalse(scan.findings)
        self.assertEqual(obs.cursors, obs.closed_cursors)
        self.assertEqual(obs.closed_connections, 1)
        self.assertTrue(obs.handler_cleared)
        with closing(sqlite3.connect(path)) as db:
            self.assertEqual(db.execute('PRAGMA journal_mode=WAL').fetchone(), ('wal',))
        with closing(sqlite3.connect(path)) as reader:
            reader.execute('BEGIN')
            reader.execute('SELECT 1 FROM sqlite_master LIMIT 1').fetchone()
            with closing(sqlite3.connect(path)) as writer:
                writer.execute('UPDATE graph_feature_evidence SET evidence_json=? WHERE run_id=?', ('{', OLD_RUNS[0])); writer.commit()
            self.assertNotEqual(reader.execute('SELECT evidence_json FROM graph_feature_evidence WHERE run_id=?', (OLD_RUNS[0],)).fetchone()[0], '{')
        with closing(sqlite3.connect(path)) as fresh:
            self.assertEqual(fresh.execute('SELECT evidence_json FROM graph_feature_evidence WHERE run_id=?', (OLD_RUNS[0],)).fetchone()[0], '{')


class IntegrityD2EvidenceAdmission(AdmissionCase):
    def test_inclusive_utf8_boundary_and_oversize_continues_history(self):
        for size, character in ((DOMAIN, 'x'), (DOMAIN + 1, '尾')):
            with self.subTest(size=size):
                path, ids = self.public()
                value, text = sized_payload(ids[0], CURRENT_RUNS[0], size, character)
                store_payload(path, CURRENT_RUNS[0], value, text=text)
                change(path, 'UPDATE graph_feature_evidence SET evidence_json=? WHERE run_id=?', ('{', OLD_RUNS[0]))
                obs = Observation(target=CURRENT_RUNS[0])
                scan = self.scan(path, obs)
                expected = [] if size == DOMAIN else [('current_evidence', 'evidence_payload_oversized', 1, 'exact')]
                expected += [('historical_evidence', 'evidence_json_invalid', 1, 'exact')]
                self.assertEqual(findings(scan), expected)
                if size > DOMAIN:
                    self.assertNotIn(CURRENT_RUNS[0], obs.value_runs, 'Oversize must never reach full-value SELECT')
                else:
                    self.assertIn(CURRENT_RUNS[0], obs.value_runs)
                self.assert_complete(scan)

    def test_utf16_exact_document_bound_not_storage_bound(self):
        for encoding, character, size in (('UTF-16le', '尾', DOMAIN), ('UTF-16be', '尾', DOMAIN + 1)):
            with self.subTest(encoding=encoding):
                path, ids = self.public(encoding, 9)
                value, text = sized_payload(ids[0], OLD_RUNS[0], size, character)
                store_payload(path, OLD_RUNS[0], value, text=text)
                obs = Observation()
                scan = self.scan(path, obs)
                self.assertEqual(findings(scan), [] if size == DOMAIN else [('historical_evidence', 'evidence_payload_oversized', 1, 'exact')])
                self.assert_complete(scan)
                if size > DOMAIN:
                    self.assertNotIn(OLD_RUNS[0], obs.value_runs)

    def test_domain_oversize_precedes_runtime32mib(self):
        path, ids = self.public()
        value, text = sized_payload(ids[0], OLD_RUNS[0], (32 << 20) + 1)
        store_payload(path, OLD_RUNS[0], value, text=text)
        obs = Observation()
        scan = self.scan(path, obs)
        self.assertEqual(findings(scan), [('historical_evidence', 'evidence_payload_oversized', 1, 'exact')])
        self.assert_complete(scan)
        self.assertNotIn(OLD_RUNS[0], obs.value_runs)
        self.assertNotIn('value_limit_reached', [f.code for f in scan.findings])

    def test_blob_bom_decoded_domain_and_separate_runtime_bound(self):
        for codec, size in (('utf-16', DOMAIN + 1), ('utf-32', 9 << 20)):
            with self.subTest(codec=codec):
                path, ids = self.public()
                value, text = sized_payload(ids[0], OLD_RUNS[0], size)
                store_payload(path, OLD_RUNS[0], value, text=text.encode(codec))
                scan = self.scan(path)
                if size > DOMAIN:
                    self.assertEqual(findings(scan), [('historical_evidence', 'evidence_payload_oversized', 1, 'exact')])
                    self.assert_complete(scan)
                else:
                    self.assertEqual(scan.stop_reason, 'value_limit')
                    self.assertFalse(scan.implemented_scope_complete)
                    self.assertIn('value_limit_reached', [f.code for f in scan.findings])
                    self.assertEqual(selected(scan, 'historical_evidence').state, 'interrupted')
                    self.assertEqual(findings(scan), [])

    def test_utf16_embedded_nul_oversized_tail_cannot_hide_from_admission(self):
        for encoding in ('UTF-16le', 'UTF-16be'):
            with self.subTest(encoding=encoding):
                path, _ = self.public(encoding)
                text = '{}\0' + 'x' * DOMAIN
                change(path, 'UPDATE graph_feature_evidence SET evidence_json=? WHERE run_id=?', (text, OLD_RUNS[0]))
                obs = Observation()
                scan = self.scan(path, obs)
                self.assertEqual(findings(scan), [('historical_evidence', 'evidence_payload_oversized', 1, 'exact')])
                self.assertNotIn(OLD_RUNS[0], obs.value_runs)
                self.assert_complete(scan)

    def test_small_blob_bom_valid_but_text_bom_is_not_stripped(self):
        for codec in ('utf-8-sig', 'utf-16', 'utf-32', 'text-bom'):
            with self.subTest(codec=codec):
                path, ids = self.public()
                value = payload(ids[0], OLD_RUNS[0])
                text = canonical(value)
                raw = '\ufeff' + text if codec == 'text-bom' else text.encode(codec)
                store_payload(path, OLD_RUNS[0], value, text=raw)
                scan = self.scan(path)
                self.assertEqual(findings(scan), [('historical_evidence', 'evidence_json_invalid', 1, 'exact')] if codec == 'text-bom' else [])
                self.assert_complete(scan)

    def test_blob_codec_raw_surrogate_and_parse_depth_suppression(self):
        for raw, code in ((b'\xffbad', 'evidence_json_invalid'),
                          (b'"\xed\xa0\x80"', 'evidence_fingerprint_invalid'),
                          (('[' * 1500 + '0' + ']' * 1500).encode(), 'evidence_contract_invalid'),
                          (('[' * 10000 + '0' + ']' * 10000).encode(), 'evidence_json_invalid')):
            with self.subTest(code=code, bytes=len(raw)):
                path, _ = self.public()
                change(path, 'UPDATE graph_feature_evidence SET evidence_json=? WHERE run_id=?', (raw, OLD_RUNS[0]))
                self.assertEqual(findings(self.scan(path)), [('historical_evidence', code, 1, 'exact')])

    def test_escaped_surrogate_and_canonical_depth_are_fingerprint_only(self):
        for case in ('surrogate', 'canonical_depth'):
            with self.subTest(case=case):
                path, ids = self.public()
                value = payload(ids[0], OLD_RUNS[0])
                if case == 'surrogate':
                    value['features']['bpm']['uncertainty'] = '\ud800'
                    text = json.dumps(value, ensure_ascii=True)
                    scan_call = lambda: self.scan(path)
                else:
                    text = canonical(value)
                    def scan_call():
                        with patch('json.dumps', canonical_target_failure):
                            return self.scan(path)
                # Canonical-depth injection is proxy-only: contract depth is
                # finite; direct control below proves intended operation fires.
                change(path, 'UPDATE graph_feature_evidence SET evidence_json=? WHERE run_id=?', (text, OLD_RUNS[0]))
                if case == 'canonical_depth':
                    with self.assertRaises(RecursionError):
                        canonical_target_failure(value, sort_keys=True, ensure_ascii=False)
                self.assertEqual(findings(scan_call()), [('historical_evidence', 'evidence_fingerprint_invalid', 1, 'exact')])

    def test_raw_sql_scalar_and_null_proxy_are_json_invalid_not_contract(self):
        for fault in ('scalar', 'null'):
            with self.subTest(fault=fault):
                path, _ = self.public()
                obs = Observation(fault=fault)
                scan = self.scan(path, obs)
                self.assertEqual(findings(scan), [('historical_evidence', 'evidence_json_invalid', 1, 'exact')])
                self.assertGreater(obs.fired, 0)
                self.assert_complete(scan)

    def test_impossible_size_and_identity_are_proxy_only_delivery_invalid(self):
        for fault in ('size', 'identity'):
            with self.subTest(fault=fault):
                path, _ = self.public()
                obs = Observation(fault=fault)
                scan = self.scan(path, obs)
                self.assertEqual(findings(scan), [('historical_evidence', 'evidence_delivery_invalid', 1, 'exact')])
                self.assertGreater(obs.fired, 0, 'Proxy must match prospective evidence SQL')

    def test_missing_admitted_value_proxy_is_one_delivery_invalid(self):
        path, _ = self.public()
        obs = Observation(fault='missing')
        scan = self.scan(path, obs)
        self.assertEqual(findings(scan), [('historical_evidence', 'evidence_delivery_invalid', 1, 'exact')])
        self.assert_complete(scan)
        self.assertEqual(obs.fired, 1, 'Missing delivered row must be actually observed after envelope admission')
        self.assertNotIn('read_failed', [f.code for f in scan.findings])
        self.assertEqual(obs.cursors, obs.closed_cursors)
        self.assertEqual(obs.closed_connections, 1)

    def test_duplicate_admitted_value_proxy_is_one_delivery_invalid(self):
        path, _ = self.public()
        obs = Observation(fault='duplicate')
        scan = self.scan(path, obs)
        self.assertEqual(findings(scan), [('historical_evidence', 'evidence_delivery_invalid', 1, 'exact')])
        self.assert_complete(scan)
        self.assertEqual(obs.fired, 1, 'Duplicate cursor row must be actually observed, not merely queued')
        self.assertNotIn('read_failed', [f.code for f in scan.findings])
        self.assertEqual(obs.cursors, obs.closed_cursors)
        self.assertEqual(obs.closed_connections, 1)
        # Duplicate operational delivery must not inflate semantic2/2 work or
        # produce multiple occurrences for the same admitted physical identity.

    def test_shared_operational_budgets_not_reset_for_evidence(self):
        path, _ = self.public()
        instances = []
        class MeteredDelivery(Delivery):
            def __init__(self, *args):
                super().__init__(*args)
                self.before_evidence = None
                instances.append(self)

            def execute(self, sql, params=()):
                if self.before_evidence is None and evidence_sql(sql):
                    self.before_evidence = self.count, self.utf8_bytes
                return super().execute(sql, params)
        # Capture phase boundary, NOT the completed evidence scan. On baseline
        # no evidence query exists, so graph exhaustion is the same boundary.
        with patch('music_analyzer.infrastructure.persistence.integrity.Delivery', MeteredDelivery):
            self.scan(path)
        meter = instances[0]
        rows, utf8 = meter.before_evidence or (meter.count, meter.utf8_bytes)
        for budget, consumed, reason, code in (
            ('MAX_ROWS', rows, 'row_limit', 'row_limit_reached'),
            ('MAX_UTF8_BYTES', utf8, 'utf8_limit', 'utf8_limit_reached'),
        ):
            with self.subTest(budget=budget):
                with patch('music_analyzer.infrastructure.persistence.integrity.' + budget, consumed + 1):
                    scan = self.scan(path)
                self.assertEqual(scan.stop_reason, reason)
                self.assertFalse(scan.implemented_scope_complete)
                self.assertEqual(selected(scan, 'current_evidence').state, 'interrupted')
                self.assertEqual(selected(scan, 'current_evidence').count_precision, 'lower_bound')
                self.assertEqual(selected(scan, 'historical_evidence').state, 'blocked')
                self.assertIn(code, [f.code for f in scan.findings])


class IntegrityD2EvidenceLateFailure(AdmissionCase):
    def test_late_corrupt_value_read_failure_both_phases_retains_prefix(self):
        for owner, run in zip(OWNERS, (CURRENT_RUNS[0], OLD_RUNS[0])):
            for fault in ('read', 'length_read'):
                with self.subTest(owner=owner, fault=fault):
                    path, _ = self.public()
                    change(path, 'UPDATE graph_feature_evidence SET evidence_json=? WHERE run_id=?', ('{', run))
                    prior = []
                    if owner == OWNERS[1]:
                        change(path, 'UPDATE graph_feature_evidence SET evidence_json=? WHERE run_id=?', ('{', CURRENT_RUNS[0]))
                        prior = [(OWNERS[0], 'evidence_json_invalid', 1, 'exact')]
                    obs = Observation(run, fault)
                    scan = self.scan(path, obs)
                    self.assertEqual(findings(scan), prior + [(owner, 'evidence_json_invalid', 1, 'lower_bound')])
                    self.assertEqual(scan.stop_reason, 'read_error')
                    self.assertFalse(scan.implemented_scope_complete)
                    self.assertEqual(selected(scan, owner).state, 'interrupted')
                    self.assertEqual(selected(scan, owner).count, 1)
                    self.assertEqual(selected(scan, owner).count_precision, 'lower_bound')
                    self.assertIn('read_failed', [f.code for f in scan.findings])
                    self.assertGreater(obs.fired, 0)
                    self.assertEqual(obs.cursors, obs.closed_cursors)
                    self.assertEqual(obs.closed_connections, 1)
                    self.assertNotIn('PRIVATE', repr(scan))
                    if owner == OWNERS[0]:
                        self.assertEqual(selected(scan, OWNERS[1]).state, 'blocked')
                    else:
                        self.assertEqual(selected(scan, OWNERS[0]).count_precision, 'exact')
                        self.assertEqual(selected(scan, OWNERS[0]).count, 2)

    def test_deadline_and_first_error_before_late_cleanup_preserve_prefix(self):
        for fault, reason, code in (('read', 'read_error', 'read_failed'), ('deadline', 'deadline', 'deadline_exceeded')):
            with self.subTest(fault=fault):
                path, _ = self.public()
                change(path, 'UPDATE graph_feature_evidence SET evidence_json=? WHERE run_id=?', ('{', OLD_RUNS[0]))
                obs = Observation(fault=fault)
                clock = [0]
                obs.on_fault = lambda: clock.__setitem__(0, 1)
                obs.on_deadline = lambda: clock.__setitem__(0, 121)
                obs.on_late_close = lambda: clock.__setitem__(0, 121)
                with patch('music_analyzer.infrastructure.persistence.integrity.monotonic', lambda: clock[0]):
                    scan = self.scan(path, obs)
                self.assertEqual(scan.stop_reason, reason)
                self.assertEqual(findings(scan), [('historical_evidence', 'evidence_json_invalid', 1, 'lower_bound')])
                self.assertIn(code, [f.code for f in scan.findings])
                if fault == 'read':
                    self.assertNotIn('deadline_exceeded', [f.code for f in scan.findings])
                self.assertEqual(selected(scan, OWNERS[0]).count_precision, 'exact')
                self.assertEqual(selected(scan, OWNERS[1]).count_precision, 'lower_bound')
                self.assertFalse(scan.implemented_scope_complete)
                self.assertGreater(obs.fired, 0)
                self.assertEqual(obs.cursors, obs.closed_cursors)
                self.assertEqual(obs.closed_connections, 1)

    def test_late_read_plus_cleanup_failure_or_cancellation_preserves_causes(self):
        for fault, reason, secondary in (('read_cleanup', 'cleanup_error', 'cleanup_failed'), ('read_cancel_cleanup', 'cancelled', 'cancelled')):
            with self.subTest(fault=fault):
                path, _ = self.public()
                change(path, 'UPDATE graph_feature_evidence SET evidence_json=? WHERE run_id=?', ('{', OLD_RUNS[0]))
                obs = Observation(fault=fault)
                scan = self.scan(path, obs)
                self.assertEqual(scan.stop_reason, reason)
                self.assertEqual(findings(scan), [('historical_evidence', 'evidence_json_invalid', 1, 'lower_bound')])
                self.assertIn('read_failed', [f.code for f in scan.findings])
                self.assertIn(secondary, [f.code for f in scan.findings])
                self.assertGreater(obs.fired, 0)
                self.assertEqual(obs.cursors, obs.closed_cursors)
                self.assertEqual(obs.closed_connections, 1)
                self.assertTrue(obs.handler_cleared)
                self.assertFalse(scan.implemented_scope_complete)
                self.assertNotIn('PRIVATE', repr(scan))

    def test_payload_processed_and_released_before_next_request_no_bulk_reads(self):
        path, _ = self.public()
        obs = Observation()
        previous = [None]
        parsed = []
        class Tracked(dict):
            pass
        real_loads = json.loads
        def loads(text, *args, **kwargs):
            value = real_loads(text, *args, **kwargs)
            if isinstance(value, dict) and value.get('feature_contract_version') == 'graph-feature-evidence-v1':
                value = Tracked(value)
                parsed.append(value['run_id'])
                previous[0] = weakref.ref(value)
            return value
        def released():
            if previous[0] is not None:
                self.assertIsNone(previous[0](), 'Previous decoded record retained at next full-value request')
        obs.before_payload_request = released
        with patch('json.loads', loads):
            scan = self.scan(path, obs)
        self.assertEqual(sorted(parsed), sorted(OLD_RUNS + CURRENT_RUNS))
        released()
        self.assert_complete(scan)
        self.assertEqual(obs.cursors, obs.closed_cursors)
        self.assertEqual(obs.closed_connections, 1)

    def test_evidence_codec_cancel_and_cleanup_keep_operational_classification(self):
        for fault, reason, code in (('codec', 'read_error', 'read_failed'), ('cancel', 'cancelled', 'cancelled'), ('cleanup', 'cleanup_error', 'cleanup_failed')):
            with self.subTest(fault=fault):
                path, _ = self.public()
                obs = Observation(fault=fault)
                scan = self.scan(path, obs)
                self.assertEqual(scan.stop_reason, reason)
                self.assertIn(code, [f.code for f in scan.findings])
                self.assertFalse(scan.implemented_scope_complete)
                self.assertEqual(selected(scan, OWNERS[1]).count_precision, 'lower_bound')
                self.assertGreater(obs.fired, 0)
                self.assertEqual(obs.closed_connections, 1)
                self.assertTrue(obs.handler_cleared)
                self.assertEqual(findings(scan), [])

    def test_scanner_pinned_snapshot_then_fresh_scan_sees_commit(self):
        path, ids = self.public()
        with closing(sqlite3.connect(path)) as db:
            db.execute('PRAGMA journal_mode=WAL').fetchone()
        committed = []
        obs = Observation(target=CURRENT_RUNS[0])
        def commit_after_first_value():
            # Scanner owns first connection; this callback owns only second.
            with closing(obs.real_connect(path)) as writer:
                writer.execute('PRAGMA foreign_keys=ON')
                writer.execute('UPDATE graph_feature_evidence SET evidence_json=? WHERE run_id=?', ('{', OLD_RUNS[0]))
                writer.execute('INSERT INTO runs(id,location,status,detail,created_at) VALUES(?,?,?,?,?)',
                               ('snapshot-newest', '/public/d1-fixture/track-1.flac', 'failed', '', '1900-01-01'))
                writer.execute('INSERT INTO run_tracks(run_id,track_id) VALUES(?,?)', ('snapshot-newest', ids[0]))
                writer.commit()
                committed.append(True)
        obs.after_value = commit_after_first_value
        scan = self.scan(path, obs)
        self.assertEqual(committed, [True], 'Barrier must really commit, not time out')
        self.assertEqual(findings(scan), [])
        self.assert_complete(scan)
        fresh = self.scan(path)
        self.assertEqual(findings(fresh), [('current_evidence', 'evidence_link_invalid', 1, 'exact'),
                                           ('historical_evidence', 'evidence_json_invalid', 1, 'exact')])
