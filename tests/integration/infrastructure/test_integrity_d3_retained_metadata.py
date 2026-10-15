"""D3a retained-only RED contracts; metadata assertions live in sibling module.

Controls run separately FIRST. No new writer DTO/raw container policy: existing
mapper plus retained validator are the acceptance oracle. Scanner RED uses real
public SQLite databases; the only fault proxy is explicitly marked operational.
"""
from contextlib import closing
from copy import deepcopy
from pathlib import Path
import json
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from music_analyzer.application.use_cases.stage_result_validation import validate_stage_result
from music_analyzer.infrastructure.persistence.stage_mapping import stage_from_mapping
from music_analyzer.infrastructure.persistence.integrity import SQLiteIntegrityScanner
from tests.integration.infrastructure.integrity_d3_public_fixture import (
    STAGE_ROWS, create_public_retained_database, replace_stage, stage_payload,
)


def retained(scan):
    return next(item for item in scan.checks if item.check_id == 'retained_stages')


def findings(scan):
    return [(item.code, item.count, item.count_precision, item.severity, item.count_unit)
            for item in scan.findings if item.check_id == 'retained_stages']


class StageCursor:
    """Transparent delegating cursor; optional first stage fetch operational fault.

    Does not rewrite SQL, rows, schema or payload. Direct controls prove target,
    non-target, EOF and close before the fault is used against scanner.
    """
    def __init__(self, cursor, owner, target):
        self.cursor, self.owner, self.target = cursor, owner, target

    def fetchone(self):
        key = 'target' if self.target else 'other'
        if self.target and self.owner.fail:
            self.owner.fired += 1
            raise sqlite3.OperationalError('public stage interruption')
        row = self.cursor.fetchone()
        self.owner.rows[key] += int(row is not None)
        self.owner.eof[key] += int(row is None)
        return row

    def __iter__(self):
        while (row := self.fetchone()) is not None:
            yield row

    def close(self):
        self.owner.closed['target' if self.target else 'other'] += 1
        return self.cursor.close()

    def __getattr__(self, name):
        return getattr(self.cursor, name)


class StageConnection:
    def __init__(self, connection, owner):
        self.connection, self.owner = connection, owner

    def execute(self, sql, *args):
        target = 'from stages' in ' '.join(sql.lower().split())
        return StageCursor(self.connection.execute(sql, *args), self.owner, target)

    def __getattr__(self, name):
        return getattr(self.connection, name)


class StageObservation:
    def __init__(self, fail=False):
        self.real_connect = sqlite3.connect
        self.fail = fail
        self.fired = 0
        self.rows = dict(target=0, other=0)
        self.eof = dict(target=0, other=0)
        self.closed = dict(target=0, other=0)

    def connect(self, *args, **kwargs):
        return StageConnection(self.real_connect(*args, **kwargs), self)


class RetainedCase(unittest.TestCase):
    def public(self, version=10):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        path = Path(temporary.name) / 'public.sqlite'
        create_public_retained_database(path, version)
        return path

    def assert_exhausted(self, scan, count=8):
        item = retained(scan)
        self.assertEqual((item.state, item.count, item.count_unit, item.count_precision),
                         ('completed', count, 'rows', 'exact'))
        self.assertEqual(scan.stop_reason, 'scope_not_implemented')

    def assert_codes(self, scan, *codes):
        self.assertEqual(findings(scan), [(code, 1, 'exact', 'corruption', 'occurrences')
                                         for code in codes])
        self.assert_exhausted(scan)


class RetainedControls(RetainedCase):
    def test_genuine_versions_and_transparent_wrapper_first(self):
        for version in range(6, 11):
            with self.subTest(version=version):
                path = self.public(version)
                observed = StageObservation()
                with closing(observed.connect(path)) as db:
                    cursor = db.execute('SELECT result FROM stages')
                    self.assertEqual(len(list(cursor)), 8)
                    cursor.close()
                    cursor = db.execute('SELECT status FROM runs')
                    self.assertEqual(len(list(cursor)), 8)
                    cursor.close()
                    self.assertEqual(db.execute('PRAGMA user_version').fetchone(), (version,))
                    self.assertEqual(db.execute('PRAGMA integrity_check').fetchone(), ('ok',))
                    self.assertIsNone(db.execute('PRAGMA foreign_key_check').fetchone())
                self.assertEqual(observed.rows['target'], 8)
                self.assertEqual(observed.eof['target'], 1)
                self.assertEqual(observed.closed['target'], 1)
                self.assertEqual(observed.rows['other'], 10)
                self.assertEqual(observed.eof['other'], 2)
                self.assertEqual(observed.closed['other'], 1)
                self.assertEqual(observed.fired, 0)
                plain = SQLiteIntegrityScanner().scan(str(path))
                with patch('music_analyzer.infrastructure.persistence.integrity.sqlite3.connect', observed.connect):
                    wrapped = SQLiteIntegrityScanner().scan(str(path))
                self.assertEqual(wrapped, plain)
                self.assertFalse(plain.findings)
                with closing(sqlite3.connect(path)) as db:
                    self.assertEqual(db.execute('SELECT status,count(*) FROM runs GROUP BY status').fetchall(),
                                     [('completed', 2), ('failed', 2), ('interrupted', 2), ('running', 2)])
                    self.assertEqual(db.execute('SELECT count(*) FROM track_metadata m JOIN locations l ON m.track_id=l.track_id WHERE l.available=0').fetchone(), (1,))

    def test_existing_mapper_predicate_preservation_controls(self):
        accepted = [stage_payload()]
        empty = stage_payload(); empty.update(values=[], windows=[], raw_predictions=[], summary=None)
        accepted.append(empty)
        no_windows = stage_payload(); no_windows['summary'] = {
            'labels': ['', ''], 'mean': [-2, -1], 'minimum': [4, 3],
            'maximum': [-8, -9], 'coverage': 1}
        accepted.append(no_windows)
        escaped = stage_payload(); escaped['values'] = [['text', '\ud800']]
        accepted.append(escaped)
        for payload in accepted:
            with self.subTest(payload=ascii(payload)):
                validate_stage_result(stage_from_mapping(payload))
        mapped = stage_from_mapping(accepted[0])
        self.assertEqual(mapped.raw_predictions, ((),))
        self.assertEqual(mapped.windows, ())
        # Actual parser recursion, not an assumed interpreter recursion threshold.
        with self.assertRaises(RecursionError):
            json.loads('[' * 20000 + '0' + ']' * 20000)

    def test_fault_proxy_hits_only_target(self):
        path = self.public()
        observed = StageObservation(fail=True)
        with closing(observed.connect(path)) as db:
            cursor = db.execute('SELECT status FROM runs')
            self.assertEqual(len(list(cursor)), 8)
            cursor.close()
            cursor = db.execute('SELECT result FROM stages')
            with self.assertRaises(sqlite3.OperationalError):
                cursor.fetchone()
            cursor.close()
        self.assertEqual(observed.fired, 1)
        self.assertEqual(observed.rows, dict(target=0, other=8))
        self.assertEqual(observed.eof, dict(target=0, other=1))
        self.assertEqual(observed.closed, dict(target=1, other=1))


class RetainedPolicyTests(RetainedCase):
    def test_all_supported_versions_drain_every_physical_row(self):
        for version in range(6, 11):
            with self.subTest(version=version):
                scan = SQLiteIntegrityScanner().scan(str(self.public(version)))
                self.assert_exhausted(scan)
                self.assertFalse(findings(scan))

    def test_optional_empty_and_negative_outputs_remain_accepted(self):
        cases = []
        empty = stage_payload(); empty.update(values=[], windows=[], raw_predictions=[], summary=None)
        cases.append(empty)
        no_windows = stage_payload(); no_windows['summary'] = {
            'labels': ['', ''], 'mean': [-2, -1], 'minimum': [4, 3],
            'maximum': [-8, -9], 'coverage': 1}
        cases.append(no_windows)
        windowed = stage_payload(); windowed.update(
            summary={'labels': ['custom'], 'mean': [-2], 'minimum': [4], 'maximum': [-8], 'coverage': 1},
            windows=[{'start': 0, 'end': 1, 'scores': [-3]}], raw_predictions=[[[4, -8]]])
        cases.append(windowed)
        for value in cases:
            with self.subTest(payload=ascii(value)):
                validate_stage_result(stage_from_mapping(value))
                path = self.public(); replace_stage(path, value)
                scan = SQLiteIntegrityScanner().scan(str(path))
                self.assertFalse(findings(scan))
                self.assert_exhausted(scan)

    def test_empty_phase_is_exact_zero(self):
        path = self.public()
        with closing(sqlite3.connect(path)) as db:
            db.execute('DELETE FROM stages'); db.commit()
        self.assert_exhausted(SQLiteIntegrityScanner().scan(str(path)), 0)

    def test_json_invalid_one_occurrence_per_row_across_all_statuses(self):
        for row, (run_id, name) in enumerate(STAGE_ROWS):
            with self.subTest(run=run_id, stage=name):
                path = self.public()
                replace_stage(path, '{invalid', row, raw=True)
                self.assert_codes(SQLiteIntegrityScanner().scan(str(path)), 'stage_json_invalid')

    def test_parse_nonobject_and_recursion_have_distinct_codes(self):
        for raw, code in [('[]', 'stage_contract_invalid'), ('null', 'stage_contract_invalid'),
                          ('[' * 20000 + '0' + ']' * 20000, 'stage_json_invalid')]:
            with self.subTest(code=code, size=len(raw)):
                path = self.public(); replace_stage(path, raw, raw=True)
                self.assert_codes(SQLiteIntegrityScanner().scan(str(path)), code)

    def test_contract_row_or_uses_existing_mapper_and_strict_predicate(self):
        base = stage_payload()
        summary = {'labels': ['x'], 'mean': [-2], 'minimum': [3], 'maximum': [-5], 'coverage': 1}
        cases = []
        for patch_value in ({'uncertainty': 2}, {'provenance': [['p', 2]]},
                            {'values': [['x', True]]}, {'raw_predictions': [[[float('inf')]]]},
                            {'windows': [{'start': 0, 'end': 1, 'scores': [1]}]},
                            {'stage': 2, 'uncertainty': 2, 'provenance': []}):
            value = deepcopy(base); value.update(patch_value); cases.append(value)
        for coverage in (0, -1, 1.01, True):
            value = deepcopy(base); value['summary'] = dict(summary, coverage=coverage); cases.append(value)
        for windows in ([{'start': 1, 'end': 0, 'scores': [1]}],
                        [{'start': 0, 'end': 2, 'scores': [1]}, {'start': 1, 'end': 3, 'scores': [1]}],
                        [{'start': 0, 'end': 1, 'scores': [True]}]):
            value = deepcopy(base); value.update(summary=summary, windows=windows); cases.append(value)
        for value in cases:
            with self.subTest(payload=ascii(value)):
                with self.assertRaises((ValueError, TypeError, KeyError)):
                    validate_stage_result(stage_from_mapping(value))
                path = self.public(); replace_stage(path, value)
                self.assert_codes(SQLiteIntegrityScanner().scan(str(path)), 'stage_contract_invalid')

    def test_identity_is_independent_only_after_successful_mapping(self):
        path = self.public(); value = stage_payload('other-custom-name')
        replace_stage(path, value)
        self.assert_codes(SQLiteIntegrityScanner().scan(str(path)), 'stage_identity_invalid')
        value['uncertainty'] = False; replace_stage(path, value)
        self.assert_codes(SQLiteIntegrityScanner().scan(str(path)), 'stage_contract_invalid')

    def test_first_retained_read_error_is_lower_bound_zero(self):
        path = self.public(); observed = StageObservation(fail=True)
        with patch('music_analyzer.infrastructure.persistence.integrity.sqlite3.connect', observed.connect):
            scan = SQLiteIntegrityScanner().scan(str(path))
        self.assertGreater(observed.fired, 0, 'scanner must attempt retained phase')
        item = retained(scan)
        self.assertEqual((item.state, item.count, item.count_precision), ('interrupted', 0, 'lower_bound'))
        self.assertEqual(scan.stop_reason, 'read_error')
        self.assertFalse(findings(scan), 'unobserved content cannot produce corruption verdict')
        self.assertGreater(observed.closed['target'], 0)
