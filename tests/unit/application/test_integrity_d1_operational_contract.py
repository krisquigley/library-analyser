"""Finite output-port safety contract; no new database validity rules."""
from dataclasses import replace
from itertools import combinations, product
from pathlib import Path
import tempfile
import unittest

from music_analyzer.application.dto.integrity import IntegrityFinding
from music_analyzer.application.use_cases.check_integrity import CheckIntegrity
from tests.unit.application.test_integrity_d1_report import (
    FakeScanner, healthy_scan, stopped_scan,
)
from tests.unit.application import test_integrity_d1_report as report_controls

OPERATIONAL = {
    'unreadable_database': 'initial_access_failed', 'read_error': 'read_failed',
    'cleanup_error': 'cleanup_failed', 'deadline': 'deadline_exceeded',
    'cancelled': 'cancelled', 'row_limit': 'row_limit_reached',
    'utf8_limit': 'utf8_limit_reached', 'value_limit': 'value_limit_reached',
    'finding_limit': 'finding_limit_reached',
}
STOPS = ('scope_not_implemented', 'unsupported_database', 'schema_blocked', *OPERATIONAL)


def operational_scan(stop, supported=False, codes=None, resource='interrupted', scope=False,
                     truncated=False):
    base = healthy_scan(6) if supported else stopped_scan('deadline')
    checks = []
    for item in base.checks:
        if item.check_id == 'resource_access':
            item = replace(item, state=resource, count={'blocked': None, 'interrupted': 0,
                           'completed': 1}[resource], count_precision={
                               'blocked': 'unavailable', 'interrupted': 'lower_bound',
                               'completed': 'exact'}[resource])
        checks.append(item)
    findings = tuple(IntegrityFinding('resource_access', code, 'operational', 1)
                     for code in (codes if codes is not None else (OPERATIONAL[stop],)))
    return replace(base, checks=tuple(checks), findings=findings, stop_reason=stop,
                   implemented_scope_complete=scope, findings_truncated=truncated)


class OperationalContract(unittest.TestCase):
    def assert_preserved(self, scan):
        report = CheckIntegrity(FakeScanner(scan)).execute('explicit-public.sqlite')
        self.assertEqual(report.stop_reason, scan.stop_reason)
        self.assertEqual(report.schema_version, scan.schema_version)
        self.assertEqual(set(report.findings), set(scan.findings))
        self.assertEqual(report.checks, scan.checks)
        self.assertEqual(report.implemented_scope_complete, scan.implemented_scope_complete)
        self.assertEqual(report.findings_truncated, scan.findings_truncated)
        self.assertEqual(report.exit_code, 130 if scan.stop_reason == 'cancelled' else (
            3 if scan.stop_reason == 'unreadable_database' else 4))
        self.assertFalse(report.complete)

    def assert_fallback(self, scan):
        report_controls.IntegrityD1RecognitionConsistency.assert_sanitized_read_error(self, scan)

    def test_single_code_stop_recognition_resource_scope_cartesian_table(self):
        for (cause, code), stop, supported, resource, scope in product(
                OPERATIONAL.items(), STOPS, (False, True),
                ('blocked', 'interrupted', 'completed'), (False, True)):
            scan = operational_scan(stop, supported, (code,), resource, scope)
            legitimate = (cause == stop and not (supported and cause == 'unreadable_database')
                          and resource != 'completed' and not scope)
            with self.subTest(cause=cause, stop=stop, supported=supported,
                              resource=resource, scope=scope):
                (self.assert_preserved if legitimate else self.assert_fallback)(scan)

    def test_all_cause_subsets_enforce_override_precedence_and_retain_prior_causes(self):
        codes = tuple(OPERATIONAL.values())
        for size in range(1, len(codes) + 1):
            for subset in combinations(codes, size):
                for supported, stop in product((False, True), OPERATIONAL):
                    legitimate = not (supported and 'initial_access_failed' in subset)
                    if 'cancelled' in subset:
                        legitimate &= stop == 'cancelled'
                    elif 'cleanup_failed' in subset:
                        legitimate &= stop == 'cleanup_error'
                    else:
                        legitimate &= OPERATIONAL[stop] in subset
                    scan = operational_scan(stop, supported, subset)
                    with self.subTest(codes=subset, supported=supported, stop=stop):
                        (self.assert_preserved if legitimate else self.assert_fallback)(scan)

    def test_every_operational_stop_requires_matching_cause(self):
        for stop, supported in product(OPERATIONAL, (False, True)):
            with self.subTest(stop=stop, supported=supported):
                self.assert_fallback(operational_scan(stop, supported, ()))

    def test_successful_resource_requires_absence_of_operational_causes(self):
        for supported in (False, True):
            base = healthy_scan(6) if supported else stopped_scan('unsupported_database')
            self.assertEqual(CheckIntegrity(FakeScanner(base)).execute('public').checks, base.checks)
            for resource in ('blocked', 'interrupted'):
                checks = tuple(replace(c, state=resource, count=None if resource == 'blocked' else 0,
                                       count_precision='unavailable' if resource == 'blocked' else 'lower_bound')
                               if c.check_id == 'resource_access' else c for c in base.checks)
                with self.subTest(supported=supported, resource=resource):
                    self.assert_fallback(replace(base, checks=checks))

    def test_truncation_retains_finding_cause_under_cleanup_and_cancellation_overrides(self):
        for supported, stop, marker in product((False, True), OPERATIONAL, (False, True)):
            codes = (OPERATIONAL[stop],)
            if marker and 'finding_limit_reached' not in codes:
                codes += ('finding_limit_reached',)
            legitimate = (stop in ('finding_limit', 'cleanup_error', 'cancelled')
                          and 'finding_limit_reached' in codes)
            scan = operational_scan(stop, supported, codes, truncated=True)
            with self.subTest(supported=supported, stop=stop, marker=marker):
                (self.assert_preserved if legitimate else self.assert_fallback)(scan)

    def test_real_sqlite_healthy_dto_cannot_claim_scope_with_operational_findings(self):
        from music_analyzer.infrastructure.persistence.integrity import SQLiteIntegrityScanner
        from tests.integration.infrastructure.integrity_d1_public_fixture import create_public_core_database
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'public.sqlite'
            create_public_core_database(path, 6)
            healthy = SQLiteIntegrityScanner().scan(str(path))
            self.assertTrue(healthy.implemented_scope_complete, 'independent real SQLite control')
            self.assertEqual(healthy.findings, ())
            for code in OPERATIONAL.values():
                with self.subTest(code=code):
                    self.assert_fallback(replace(healthy, findings=(
                        IntegrityFinding('resource_access', code, 'operational', 1),)))

    def test_real_elapsed_pre_recognition_deadline_cannot_be_relabeled_unreadable(self):
        from music_analyzer.infrastructure.persistence.integrity import SQLiteIntegrityScanner
        with tempfile.TemporaryDirectory() as td:
            scan = SQLiteIntegrityScanner().scan(str(Path(td) / 'not-opened.sqlite'), 1e-12)
        self.assertEqual(scan.stop_reason, 'deadline', 'actual elapsed deadline control')
        self.assertIsNone(scan.schema_version)
        self.assertEqual(tuple(f.code for f in scan.findings), ('deadline_exceeded',))
        self.assert_preserved(scan)
        self.assert_fallback(replace(scan, stop_reason='unreadable_database'))

    def test_non_operational_stops_preserve_legitimate_schema_and_unsupported_results(self):
        healthy = healthy_scan(6)
        schema_finding = IntegrityFinding('schema', 'schema_checks_mismatch', 'corruption', 1,
                                          count_precision='exact')
        checks = tuple(replace(c, state='blocked', count=None, count_precision='unavailable')
                       if c.check_id in ('core_rows', 'metadata', 'retained_stages', 'sqlite_physical', 'sqlite_foreign_keys') else c for c in healthy.checks)
        schema_blocked = replace(healthy, checks=checks, findings=(schema_finding,),
                                 stop_reason='schema_blocked', implemented_scope_complete=False)
        report = CheckIntegrity(FakeScanner(schema_blocked)).execute('public')
        self.assertEqual((report.stop_reason, report.findings), ('schema_blocked', (schema_finding,)))
        for base in (healthy, schema_blocked, stopped_scan('unsupported_database')):
            for code in OPERATIONAL.values():
                with self.subTest(stop=base.stop_reason, code=code):
                    self.assert_fallback(replace(base, findings=base.findings + (
                        IntegrityFinding('resource_access', code, 'operational', 1),)))

    def test_propagated_cancellation_remains_130(self):
        class Cancelled:
            def scan(self, database, deadline_seconds):
                raise KeyboardInterrupt
        report = CheckIntegrity(Cancelled()).execute('public')
        self.assertEqual((report.stop_reason, report.exit_code), ('cancelled', 130))
        self.assertEqual(tuple(f.code for f in report.findings), ('cancelled',))
