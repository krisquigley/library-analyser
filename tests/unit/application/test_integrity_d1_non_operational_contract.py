"""Approved stop-label prerequisites at the application output boundary only."""
from contextlib import closing
from dataclasses import replace
from pathlib import Path
import sqlite3
import tempfile
import unittest

from music_analyzer.application.dto.integrity import IntegrityFinding
from music_analyzer.application.use_cases.check_integrity import CheckIntegrity
from music_analyzer.infrastructure.persistence.integrity import SQLiteIntegrityScanner
from tests.integration.infrastructure.integrity_d1_public_fixture import create_public_core_database
from tests.unit.application.test_integrity_d1_report import FakeScanner, healthy_scan, stopped_scan


class NonOperationalContract(unittest.TestCase):
    def actual_scan(self, kind):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'public.sqlite'
            create_public_core_database(path, 6)
            if kind != 'healthy':
                with closing(sqlite3.connect(path)) as db:
                    if kind == 'unknown':
                        db.execute('PRAGMA user_version=123')
                    else:
                        db.execute('CREATE TABLE public_extra(value INTEGER)')
                    db.commit()
            return SQLiteIntegrityScanner().scan(str(path))

    def assert_preserved(self, scan):
        report = CheckIntegrity(FakeScanner(scan)).execute('public.sqlite')
        self.assertEqual((report.stop_reason, report.schema_version, report.checks,
                          report.findings, report.implemented_scope_complete),
                         (scan.stop_reason, scan.schema_version, scan.checks,
                          scan.findings, scan.implemented_scope_complete))

    def assert_fallback(self, scan):
        report = CheckIntegrity(FakeScanner(scan)).execute('public.sqlite')
        self.assertEqual(report.stop_reason, 'read_error')
        self.assertEqual((report.status, report.exit_code, report.schema_version,
                          report.complete, report.implemented_scope_complete,
                          report.findings_truncated), ('incomplete', 4, None, False, False, False))
        expected = stopped_scan('read_error')
        # The fallback blocks ALL semantic checks, including compatibility.
        checks = tuple(replace(c, state='blocked', count=None, count_precision='unavailable')
                       if c.check_id == 'compatibility' else c for c in expected.checks)
        self.assertEqual(report.checks, checks)
        self.assertEqual(report.findings, (IntegrityFinding('resource_access', 'read_failed',
                                                           'operational', 1),))

    def test_actual_healthy_v6_cannot_be_relabeled_schema_blocked(self):
        scan = self.actual_scan('healthy')
        self.assertEqual(scan.stop_reason, 'completed')
        self.assertTrue(scan.implemented_scope_complete)
        self.assertEqual(scan.schema_version, 6)
        self.assertEqual(scan.findings, ())
        self.assertEqual(next(c.state for c in scan.checks if c.check_id == 'core_rows'), 'completed')
        self.assert_preserved(scan)
        self.assert_fallback(replace(scan, stop_reason='schema_blocked', implemented_scope_complete=False))

    def test_actual_unrecognized_version_cannot_be_relabeled_schema_blocked(self):
        scan = self.actual_scan('unknown')
        self.assertEqual(scan.stop_reason, 'unsupported_database')
        self.assertIsNone(scan.schema_version)
        self.assertFalse(scan.supported)
        self.assertEqual(tuple(f.code for f in scan.findings), ('schema_version_unsupported',))
        self.assert_preserved(scan)
        self.assert_fallback(replace(scan, stop_reason='schema_blocked'))

    def test_actual_schema_drift_is_preserved(self):
        scan = self.actual_scan('drift')
        self.assertEqual(scan.stop_reason, 'schema_blocked')
        self.assertEqual(scan.schema_version, 6)
        self.assertFalse(scan.implemented_scope_complete)
        self.assertEqual(tuple(f.code for f in scan.findings), ('schema_object_set_mismatch',))
        self.assertEqual(next(c.state for c in scan.checks if c.check_id == 'core_rows'), 'blocked')
        self.assert_preserved(scan)

    def test_unsupported_database_cannot_claim_schema_or_core_findings(self):
        base = stopped_scan('unsupported_database')
        for check, code in (('schema', 'schema_checks_mismatch'), ('core_rows', 'track_size_invalid')):
            with self.subTest(check=check):
                self.assert_fallback(replace(base, findings=base.findings + (
                    IntegrityFinding(check, code, 'corruption', 1),)))

    def test_schema_blocked_requires_drift_and_no_interrupted_schema_work(self):
        base = healthy_scan(6)
        blocked_core = tuple(replace(c, state='blocked', count=None, count_precision='unavailable')
                             if c.check_id in ('core_rows', 'metadata', 'retained_stages') else c for c in base.checks)
        drift = replace(base, checks=blocked_core, implemented_scope_complete=False,
                        stop_reason='schema_blocked', findings=(IntegrityFinding(
                            'schema', 'schema_checks_mismatch', 'corruption', 1),))
        self.assert_preserved(drift)
        self.assert_fallback(replace(drift, findings=()))

    def test_schema_blocked_cannot_claim_interrupted_schema_work(self):
        base = healthy_scan(6)
        drift = replace(base, checks=tuple(replace(c, state='blocked', count=None,
                        count_precision='unavailable') if c.check_id in ('core_rows', 'metadata', 'retained_stages') else c
                        for c in base.checks), implemented_scope_complete=False,
                        stop_reason='schema_blocked', findings=(IntegrityFinding(
                            'schema', 'schema_checks_mismatch', 'corruption', 1),))
        interrupted = tuple(replace(c, state='interrupted', count_precision='lower_bound')
                            if c.check_id == 'schema' else c for c in drift.checks)
        self.assert_fallback(replace(drift, checks=interrupted))

    def test_other_non_operational_prerequisites_and_initial_unreadable(self):
        healthy = healthy_scan(6)
        unsupported = stopped_scan('unsupported_database')
        unreadable = stopped_scan('unreadable_database')
        for scan in (healthy, unsupported, unreadable):
            self.assert_preserved(scan)
        cases = (
            replace(unsupported, stop_reason='scope_not_implemented'),
            replace(unsupported, findings=()),
            replace(healthy, stop_reason='unsupported_database', implemented_scope_complete=False),
            replace(unreadable, findings=()),
            replace(healthy, stop_reason='unreadable_database', implemented_scope_complete=False),
            replace(unreadable, stop_reason='scope_not_implemented'),
        )
        for scan in cases:
            with self.subTest(stop=scan.stop_reason, supported=scan.supported):
                self.assert_fallback(scan)
