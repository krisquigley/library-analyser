"""Approved A+B tests-only RED on the existing scanner seam.

Small independent public records, not a corruption certificate. Exact expected
codes are literals, not obtained from production validators or exception text.
Constraint-impossible NULL/duplicate cases are labelled proxy/review-only.
"""
from contextlib import closing
from copy import deepcopy
from pathlib import Path
import json
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from music_analyzer.infrastructure.persistence.integrity import SQLiteIntegrityScanner
from music_analyzer.infrastructure.persistence.explorer_readonly import ReadOnlyExplorerSQLiteRepository as AnalyzerReader
from music_explorer.infrastructure.explorer_readonly import ReadOnlyExplorerSQLiteRepository as StandaloneReader
from tests.integration.infrastructure.integrity_d1_public_fixture import create_public_core_database
from tests.integration.infrastructure.integrity_d2_evidence_public_fixture import (
    create_public_evidence_database, OLD_RUNS, CURRENT_RUNS, payload, stage,
    summary, canonical, fingerprint, store_payload, change,
)

OWNERS = ('current_evidence', 'historical_evidence')
CODES = ('evidence_envelope_invalid', 'evidence_link_invalid',
         'evidence_json_invalid', 'evidence_contract_invalid',
         'evidence_feature_invalid', 'evidence_summary_invalid',
         'evidence_fingerprint_invalid', 'evidence_delivery_invalid',
         'evidence_payload_oversized')


def check(scan, owner):
    return next(item for item in scan.checks if item.check_id == owner)


def evidence_findings(scan):
    return [(f.check_id, f.code, f.count, f.count_precision) for f in scan.findings
            if f.check_id in OWNERS]


class EvidenceCursor:
    """NULL flag proxy only: genuine NOT NULL schema cannot store this row.

    Matching actual evidence SELECT columns, not unrelated graph descriptors.
    No exception is injected; direct selfcontrol proves match and firing.
    """
    def __init__(self, cursor, owner, matched):
        self.cursor, self.owner, self.matched = cursor, owner, matched

    def fetchone(self):
        row = self.cursor.fetchone()
        if row is not None and self.matched:
            columns = [item[0] for item in self.cursor.description]
            if 'is_current' in columns and 'run_id' in columns:
                if row[columns.index('run_id')] == OLD_RUNS[0]:
                    self.owner.matched += 1
                    if self.owner.null_flag:
                        row = list(row)
                        row[columns.index('is_current')] = None
                        row = tuple(row)
                        self.owner.fired += 1
        return row

    def __iter__(self):
        while (row := self.fetchone()) is not None:
            yield row

    def __getattr__(self, name):
        return getattr(self.cursor, name)


class EvidenceConnection:
    def __init__(self, connection, observation):
        self.connection, self.observation = connection, observation

    def execute(self, sql, *args):
        return EvidenceCursor(self.connection.execute(sql, *args), self.observation,
                              'graph_feature_evidence' in sql.lower() and
                              sql.lstrip().upper().startswith('SELECT'))

    def __getattr__(self, name):
        return getattr(self.connection, name)


class EvidenceObservation:
    def __init__(self, null_flag=False):
        self.real_connect = sqlite3.connect
        self.null_flag = null_flag
        self.matched = self.fired = 0

    def connect(self, *args, **kwargs):
        return EvidenceConnection(self.real_connect(*args, **kwargs), self)


class EvidenceCase(unittest.TestCase):
    def public(self, version=10):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        path = Path(temporary.name) / 'public.sqlite'
        ids = create_public_evidence_database(path, version)
        return path, ids

    def assert_exhausted(self, scan, counts=(2, 2)):
        for owner, count in zip(OWNERS, counts):
            item = check(scan, owner)
            self.assertEqual((item.state, item.count, item.count_unit, item.count_precision),
                             ('completed', count, 'rows', 'exact'), owner)
        self.assertTrue(scan.implemented_scope_complete)
        self.assertEqual(scan.stop_reason, 'scope_not_implemented')

    def assert_codes(self, scan, owner, codes, counts=None):
        expected = [(owner, code, 1 if counts is None else counts.get(code, 1), 'exact')
                    for code in CODES if code in codes]
        self.assertEqual(evidence_findings(scan), expected)
        for finding in scan.findings:
            if finding.check_id in OWNERS:
                self.assertEqual((finding.severity, finding.count_unit), ('corruption', 'occurrences'))
        self.assert_exhausted(scan)


class IntegrityD2EvidenceControls(EvidenceCase):
    def test_genuine_versions_physical_fk_order_and_full_readers(self):
        for version in range(6, 11):
            with self.subTest(version=version):
                path, ids = self.public(version)
                with closing(sqlite3.connect(path)) as db:
                    self.assertEqual(db.execute('PRAGMA user_version').fetchone(), (version,))
                    self.assertEqual(db.execute('PRAGMA integrity_check').fetchall(), [('ok',)])
                    self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(), [])
                    if version >= 9:
                        self.assertEqual(db.execute('SELECT is_current,count(*) FROM graph_feature_evidence GROUP BY is_current').fetchall(), [(0, 2), (1, 2)])
                        for old, current in zip(OLD_RUNS, CURRENT_RUNS):
                            old_id = db.execute('SELECT rowid FROM runs WHERE id=?', (old,)).fetchone()[0]
                            new_id = db.execute('SELECT rowid FROM runs WHERE id=?', (current,)).fetchone()[0]
                            self.assertLess(old_id, new_id)
                        self.assertEqual(db.execute('SELECT count(*) FROM graph_build_edges').fetchone(), (2,))
                scan = SQLiteIntegrityScanner().scan(str(path))
                self.assertFalse(scan.findings)
                self.assertEqual(check(scan, 'schema').state, 'completed')
                if version >= 7:
                    self.assertEqual((check(scan, 'current_graph').count, check(scan, 'historical_graph').count), (2 if version == 7 else 3, 4 if version == 7 else 8))
                for reader_type in (AnalyzerReader, StandaloneReader):
                    self.assertEqual(reader_type(str(path)).track_ids(), ids)

    def test_empty_and_legacy_applicability_controls(self):
        for version in range(6, 11):
            with self.subTest(version=version), tempfile.TemporaryDirectory() as td:
                path = Path(td) / 'empty.sqlite'
                create_public_core_database(path, version)
                scan = SQLiteIntegrityScanner().scan(str(path))
                self.assertFalse(scan.findings)
                if version < 9:
                    for owner in OWNERS:
                        item = check(scan, owner)
                        self.assertEqual((item.state, item.count, item.count_precision),
                                         ('not_applicable', None, 'unavailable'))

    def test_schema_blocks_duplicate_current_and_null_without_ddl_drift(self):
        path, _ = self.public()
        with closing(sqlite3.connect(path)) as db:
            ddl = db.execute("SELECT sql FROM sqlite_master ORDER BY name").fetchall()
            db.execute('PRAGMA ignore_check_constraints=ON')
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute('UPDATE graph_feature_evidence SET is_current=1 WHERE run_id=?', (OLD_RUNS[0],))
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute('UPDATE graph_feature_evidence SET is_current=NULL WHERE run_id=?', (OLD_RUNS[0],))
            self.assertEqual(db.execute('SELECT sql FROM sqlite_master ORDER BY name').fetchall(), ddl)
        # Review-only physical impossibility; not a scanner corruption RED.

    def test_null_proxy_direct_firing_and_healthy_scanner_wrapper(self):
        path, _ = self.public()
        for enabled in (False, True):
            observed = EvidenceObservation(null_flag=enabled)
            with closing(observed.connect(path)) as db:
                cursor = db.execute('SELECT run_id,is_current FROM graph_feature_evidence WHERE run_id=?', (OLD_RUNS[0],))
                self.assertEqual(cursor.fetchone(), (OLD_RUNS[0], None if enabled else 0))
                self.assertIsNone(cursor.fetchone())
                cursor.close()
            self.assertEqual((observed.matched, observed.fired), (1, int(enabled)))
        observed = EvidenceObservation()
        with patch('sqlite3.connect', observed.connect):
            self.assertFalse(SQLiteIntegrityScanner().scan(str(path)).findings)


class IntegrityD2EvidenceEnvelope(EvidenceCase):
    def test_populated_and_empty_semantic_counts(self):
        for version in (9, 10):
            for populated in (True, False):
                with self.subTest(version=version, populated=populated), tempfile.TemporaryDirectory() as td:
                    path = Path(td) / 'public.sqlite'
                    (create_public_evidence_database if populated else create_public_core_database)(path, version)
                    self.assert_exhausted(SQLiteIntegrityScanner().scan(str(path)), (2, 2) if populated else (0, 0))

    def test_flag_numeric_membership_and_disjoint_invalid_remainder(self):
        for flag in (2, 'invalid', b'1'):
            for version in (9, 10):
                with self.subTest(flag=flag, version=version):
                    path, _ = self.public(version)
                    change(path, 'UPDATE graph_feature_evidence SET is_current=? WHERE run_id=?', (flag, OLD_RUNS[0]), corrupt=True)
                    with closing(sqlite3.connect(path)) as db:
                        self.assertEqual(db.execute('SELECT is_current FROM graph_feature_evidence WHERE run_id=?', (OLD_RUNS[0],)).fetchone(), (flag,))
                    self.assert_codes(SQLiteIntegrityScanner().scan(str(path)), 'historical_evidence', ['evidence_envelope_invalid'])

    def test_invalid_current_flag_moves_row_to_historical_owner(self):
        path, _ = self.public()
        change(path, 'UPDATE graph_feature_evidence SET is_current=2 WHERE run_id=?',
               (CURRENT_RUNS[0],), corrupt=True)
        scan = SQLiteIntegrityScanner().scan(str(path))
        self.assertEqual(evidence_findings(scan),
                         [('historical_evidence', 'evidence_envelope_invalid', 1, 'exact')])
        self.assert_exhausted(scan, (1, 3))

    def test_null_flag_proxy_only_historical_envelope(self):
        path, _ = self.public()
        observed = EvidenceObservation(null_flag=True)
        with patch('sqlite3.connect', observed.connect):
            scan = SQLiteIntegrityScanner().scan(str(path))
        self.assert_codes(scan, 'historical_evidence', ['evidence_envelope_invalid'])
        self.assertGreater(observed.fired, 0)

    def test_envelope_identity_or_once_per_row_with_independent_links(self):
        for current in (False, True):
            with self.subTest(current=current):
                path, _ = self.public()
                run = CURRENT_RUNS[0] if current else OLD_RUNS[0]
                change(path, 'UPDATE graph_feature_evidence SET track_id=?,run_id=?,evidence_json=? WHERE run_id=?',
                       ('BAD', '', '{', run), corrupt=True)
                self.assert_codes(SQLiteIntegrityScanner().scan(str(path)), OWNERS[0 if current else 1],
                                  ['evidence_envelope_invalid', 'evidence_link_invalid', 'evidence_json_invalid'])

    def test_historical_links_missing_run_pair_and_noncompleted(self):
        for kind in ('missing_run', 'missing_pair', 'running', 'failed', 'interrupted'):
            with self.subTest(kind=kind):
                path, _ = self.public(9)
                if kind == 'missing_run':
                    change(path, 'DELETE FROM runs WHERE id=?', (OLD_RUNS[0],), corrupt=True)
                elif kind == 'missing_pair':
                    change(path, 'DELETE FROM run_tracks WHERE run_id=?', (OLD_RUNS[0],))
                else:
                    change(path, 'UPDATE runs SET status=? WHERE id=?', (kind, OLD_RUNS[0]))
                self.assert_codes(SQLiteIntegrityScanner().scan(str(path)), 'historical_evidence', ['evidence_link_invalid'])

    def test_current_newest_rowid_includes_noncompleted_and_ignores_timestamp(self):
        for status in ('completed', 'failed', 'running', 'interrupted'):
            with self.subTest(status=status):
                path, ids = self.public()
                with closing(sqlite3.connect(path)) as db:
                    db.execute('PRAGMA foreign_keys=ON')
                    db.execute('INSERT INTO runs(id,location,status,detail,created_at) VALUES(?,?,?,?,?)',
                               ('aaa-newest', '/public/d1-fixture/track-1.flac', status, '', '1900-01-01'))
                    db.execute('INSERT INTO run_tracks(run_id,track_id) VALUES(?,?)', ('aaa-newest', ids[0]))
                    db.commit()
                self.assert_codes(SQLiteIntegrityScanner().scan(str(path)), 'current_evidence', ['evidence_link_invalid'])

    def test_old_corruption_and_current_corruption_are_disjoint(self):
        path, _ = self.public()
        for run in (OLD_RUNS[0], CURRENT_RUNS[1]):
            change(path, 'UPDATE graph_feature_evidence SET evidence_json=? WHERE run_id=?', ('{', run))
        scan = SQLiteIntegrityScanner().scan(str(path))
        self.assertEqual(evidence_findings(scan), [(owner, 'evidence_json_invalid', 1, 'exact') for owner in OWNERS])
        self.assert_exhausted(scan)


# Literal path mutation tables: no production predicate computes expectations.
def replace(value, path, replacement):
    target = value
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = deepcopy(replacement)


FEATURE_CASES = (
    ('features_type', ('features',), []),
    ('features_keys', ('features',), {}),
    ('stage_type', ('features', 'key'), '8A'),
    ('stage_keys', ('features', 'key'), {}),
    ('provenance_type', ('features', 'bpm', 'provenance'), {}),
    ('provenance_pair', ('features', 'bpm', 'provenance'), [['', 'ok']]),
    ('provenance_value', ('features', 'bpm', 'provenance'), [['source', 1]]),
    ('uncertainty', ('features', 'bpm', 'uncertainty'), 1),
    ('bpm_bool', ('features', 'bpm', 'values'), [['bpm', True]]),
    ('bpm_nonfinite', ('features', 'bpm', 'values'), [['bpm', float('nan')]]),
    ('bpm_pair', ('features', 'bpm', 'values'), [['bpm']]),
    ('scalar_summary', ('features', 'bpm', 'summary'), summary()),
    ('scalar_summary_values_nonsequence', ('features', 'bpm', 'summary_values'), 7),
    ('key_duplicate', ('features', 'key', 'values'), [['key', 'A'], ['key', 'B']]),
    ('key_unknown', ('features', 'key', 'values'), [['unknown', 'A']]),
    ('key_empty', ('features', 'key', 'values'), [['scale', '']]),
    ('key_bool', ('features', 'key', 'values'), [['strength', True]]),
    ('genres_numeric', ('features', 'genres', 'values'), [['genre', 1]]),
    ('genres_summary_values', ('features', 'genres', 'summary_values'), [['x', 0.5]]),
)
SUMMARY_CASES = (
    ('values_forbidden', ('values',), [['x', 1]]),
    ('summary_type', ('summary',), 1),
    ('summary_keys', ('summary',), {}),
    ('labels_empty', ('summary', 'labels'), []),
    ('labels_duplicate', ('summary', 'labels'), ['x', 'x']),
    ('labels_bad', ('summary', 'labels'), ['']),
    ('mean_length', ('summary', 'mean'), []),
    ('mean_bool', ('summary', 'mean'), [True]),
    ('minimum_type', ('summary', 'minimum'), 'x'),
    ('maximum_nonfinite', ('summary', 'maximum'), [float('inf')]),
    ('coverage_low', ('summary', 'coverage'), -0.1),
    ('coverage_high', ('summary', 'coverage'), 1.1),
    ('coverage_bool', ('summary', 'coverage'), True),
    ('provisional_int', ('summary', 'provisional'), 1),
    ('uncertainty_type', ('summary', 'uncertainty'), []),
    ('zip_mismatch', ('summary_values',), [['other', 0.5]]),
    ('zip_nonsequence', ('summary_values',), 1),
)


class IntegrityD2EvidencePayloadControls(EvidenceCase):
    def test_permissive_valid_variants_and_canonical_storage(self):
        for variant in ('empty', 'permissive', 'summary_genres', 'duplicate_json_keys', 'whitespace'):
            with self.subTest(variant=variant):
                path, ids = self.public()
                value = payload(ids[0], CURRENT_RUNS[0])
                if variant == 'empty':
                    value['features'] = {name: stage() for name in ('bpm', 'key', 'genres', 'mood', 'energy')}
                elif variant == 'permissive':
                    value['features']['bpm']['values'] = [['自由', -2], ['自由', -2]]
                    value['features']['key']['values'] = [['coverage', 9], ['scale', 'arbitrary']]
                    value['features']['genres']['values'] = [['g', 'x'], ['g', 'x']]
                    value['features']['mood']['summary'].update(mean=[3], minimum=[7], maximum=[-4], coverage=0)
                    value['features']['mood']['summary_values'] = [['public', 3]]
                    value['features']['bpm']['provenance'] = [['source', '']]
                elif variant == 'summary_genres':
                    value['features']['genres'] = stage(summary=summary())
                text = canonical(value)
                if variant == 'whitespace':
                    text = json.dumps(value, ensure_ascii=False, indent=2)
                elif variant == 'duplicate_json_keys':
                    text = '{"feature_contract_version":"ignored",' + text[1:]
                store_payload(path, CURRENT_RUNS[0], value, text=text)
                self.assertFalse(SQLiteIntegrityScanner().scan(str(path)).findings)
                for reader_type in (AnalyzerReader, StandaloneReader):
                    self.assertEqual(reader_type(str(path)).track_ids(), ids)

    def test_retained_raw_stages_do_not_become_compact_findings(self):
        path, _ = self.public()
        with closing(sqlite3.connect(path)) as db:
            db.execute('PRAGMA foreign_keys=ON')
            db.execute('INSERT INTO stages(run_id,stage,result) VALUES(?,?,?)',
                       (OLD_RUNS[0], 'mood', '{PRIVATE invalid retained raw JSON'))
            db.commit()
        scan = SQLiteIntegrityScanner().scan(str(path))
        self.assertFalse(scan.findings)
        self.assertEqual(check(scan, 'retained_stages').state, 'not_implemented')

    def test_numeric_flags_and_missing_compact_rows_are_not_hardened(self):
        path, ids = self.public()
        change(path, 'UPDATE graph_feature_evidence SET is_current=1.0 WHERE run_id=?', (CURRENT_RUNS[0],))
        change(path, 'DELETE FROM graph_feature_evidence WHERE run_id=?', (CURRENT_RUNS[1],))
        change(path, 'UPDATE locations SET available=0 WHERE track_id=?', (ids[0],))
        self.assertFalse(SQLiteIntegrityScanner().scan(str(path)).findings)


class IntegrityD2EvidencePayload(EvidenceCase):
    def test_json_rejection_suppresses_contract_feature_and_hash(self):
        for text in ('{', 'null', '[]', '42', '"text"'):
            with self.subTest(text=text):
                path, _ = self.public(9)
                change(path, 'UPDATE graph_feature_evidence SET evidence_json=? WHERE run_id=?', (text, OLD_RUNS[0]))
                # Non-object valid JSON is contract-invalid, not parse-invalid.
                code = 'evidence_json_invalid' if text == '{' else 'evidence_contract_invalid'
                self.assert_codes(SQLiteIntegrityScanner().scan(str(path)), 'historical_evidence', [code])

    def test_exact_top_contract_and_identity_suppression(self):
        for name, mutation in (('extra', lambda v: v.update(extra=1)),
                               ('missing', lambda v: v.pop('features')),
                               ('version', lambda v: v.update(feature_contract_version='wrong')),
                               ('track', lambda v: v.update(track_id='other')),
                               ('run', lambda v: v.update(run_id='other'))):
            with self.subTest(name=name):
                path, ids = self.public()
                value = payload(ids[0], CURRENT_RUNS[0]); mutation(value)
                store_payload(path, CURRENT_RUNS[0], value)
                self.assert_codes(SQLiteIntegrityScanner().scan(str(path)), 'current_evidence', ['evidence_contract_invalid'])

    def test_common_scalar_key_and_genre_feature_table(self):
        for index, (name, keys, replacement) in enumerate(FEATURE_CASES):
            with self.subTest(name=name):
                path, ids = self.public(9 if index % 2 else 10)
                run = OLD_RUNS[0] if index % 2 else CURRENT_RUNS[0]
                value = payload(ids[0], run); replace(value, keys, replacement)
                # Nonfinite content cannot canonical-hash: syntactically valid
                # stored digest stays independent, hash suppressed by feature.
                if name == 'bpm_nonfinite':
                    store_payload(path, run, value, text=json.dumps(value), digest='a' * 64)
                else:
                    store_payload(path, run, value)
                self.assert_codes(SQLiteIntegrityScanner().scan(str(path)), 'historical_evidence' if index % 2 else 'current_evidence', ['evidence_feature_invalid'])

    def test_summary_shape_pairing_and_finite_table(self):
        for index, (name, keys, replacement) in enumerate(SUMMARY_CASES):
            with self.subTest(name=name):
                path, ids = self.public()
                value = payload(ids[0], OLD_RUNS[0])
                feature = ('mood', 'energy', 'genres')[index % 3]
                value['features'][feature] = stage(summary=summary())
                replace(value['features'][feature], keys, replacement)
                if name == 'maximum_nonfinite':
                    store_payload(path, OLD_RUNS[0], value, text=json.dumps(value), digest='a' * 64)
                else:
                    store_payload(path, OLD_RUNS[0], value)
                self.assert_codes(SQLiteIntegrityScanner().scan(str(path)), 'historical_evidence', ['evidence_summary_invalid'])
        for invalid in (None, 1, [['x', 1]]):
            with self.subTest(absent_summary_values=invalid):
                path, ids = self.public()
                value = payload(ids[0], OLD_RUNS[0]); value['features']['mood'] = stage()
                value['features']['mood']['summary_values'] = invalid
                store_payload(path, OLD_RUNS[0], value)
                self.assert_codes(SQLiteIntegrityScanner().scan(str(path)), 'historical_evidence', ['evidence_summary_invalid'])

    def test_fingerprint_syntax_and_canonical_mismatch_or_once(self):
        for digest in ('A' * 64, 'short', '0' * 64):
            with self.subTest(digest=digest):
                path, _ = self.public()
                change(path, 'UPDATE graph_feature_evidence SET fingerprint=? WHERE run_id=?', (digest, OLD_RUNS[0]))
                self.assert_codes(SQLiteIntegrityScanner().scan(str(path)), 'historical_evidence', ['evidence_fingerprint_invalid'])

    def test_multi_code_independence_or_per_row_and_parent_suppression(self):
        path, ids = self.public()
        value = payload(ids[0], OLD_RUNS[0])
        value['features']['bpm']['values'] = [['bpm', True]]
        value['features']['key']['values'] = [['key', '']]
        value['features']['mood']['summary']['coverage'] = 2
        value['features']['energy']['summary']['coverage'] = -1
        store_payload(path, OLD_RUNS[0], value, digest='BAD')
        # Two fields/stages in a category still one occurrence. Independent
        # syntax remains; invalid content suppresses only canonical hash.
        self.assert_codes(SQLiteIntegrityScanner().scan(str(path)), 'historical_evidence',
                          ['evidence_feature_invalid', 'evidence_summary_invalid', 'evidence_fingerprint_invalid'])

    def test_common_shape_suppresses_child_summary_and_hash(self):
        path, ids = self.public()
        value = payload(ids[0], OLD_RUNS[0])
        value['features']['mood'] = {'summary': {'coverage': 99}}
        store_payload(path, OLD_RUNS[0], value)
        self.assert_codes(SQLiteIntegrityScanner().scan(str(path)), 'historical_evidence', ['evidence_feature_invalid'])


class IntegrityD2EvidenceSummaryParity(EvidenceCase):
    """Genuine v10 records retain established equality-only summary semantics."""
    def test_numeric_equality_healthy_control(self):
        path, _ = self.public()
        scan = SQLiteIntegrityScanner().scan(str(path))
        self.assertFalse(scan.findings)
        self.assert_exhausted(scan)

    def test_true_one_and_false_zero_summary_equality(self):
        for mean, displayed in ((1, True), (0, False)):
            with self.subTest(mean=mean, displayed=displayed):
                path, ids = self.public()
                value = payload(ids[0], CURRENT_RUNS[0])
                mood = value['features']['mood']
                mood['summary']['mean'] = [mean]
                mood['summary_values'] = [['public', displayed]]
                store_payload(path, CURRENT_RUNS[0], value)
                scan = SQLiteIntegrityScanner().scan(str(path))
                self.assertFalse(scan.findings)
                self.assert_exhausted(scan)

    def test_unequal_boolean_summary_control(self):
        path, ids = self.public()
        value = payload(ids[0], CURRENT_RUNS[0])
        value['features']['mood']['summary']['mean'] = [0]
        value['features']['mood']['summary_values'] = [['public', True]]
        store_payload(path, CURRENT_RUNS[0], value)
        self.assert_codes(SQLiteIntegrityScanner().scan(str(path)), 'current_evidence',
                          ['evidence_summary_invalid'])
