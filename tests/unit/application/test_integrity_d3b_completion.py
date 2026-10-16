"""D3 completion policy through pure inward fake ports; no SQLite."""
from dataclasses import replace
import unittest
import sys

from music_analyzer.application.dto.integrity import IntegrityCheck, IntegrityFinding, IntegrityScan
from music_analyzer.application.use_cases.check_integrity import CheckIntegrity

# Independent literal approved order, units and genuine schema applicability.
CHECKS = (
    ('compatibility', 'databases', 6), ('schema', 'schema_descriptors', 6),
    ('core_rows', 'rows', 6), ('metadata', 'rows', 6), ('retained_stages', 'rows', 6),
    ('current_graph', 'rows', 7), ('historical_graph', 'rows', 7),
    ('current_evidence', 'rows', 9), ('historical_evidence', 'rows', 9),
    ('sqlite_physical', 'physical_records', 6),
    ('sqlite_foreign_keys', 'foreign_key_records', 6), ('resource_access', 'databases', 6),
)


def completed_scan(version=10):
    checks = tuple(IntegrityCheck(name, name,
                                 'completed' if version >= first else 'not_applicable',
                                 (1 if name in ('compatibility', 'resource_access', 'sqlite_physical') else 0)
                                 if version >= first else None,
                                 unit, 'exact' if version >= first else 'unavailable')
                   for name, unit, first in CHECKS)
    return IntegrityScan(version, checks, implemented_scope_complete=True, stop_reason='completed')


def changed(scan, owner, **fields):
    return replace(scan, checks=tuple(replace(c, **fields) if c.check_id == owner else c
                                     for c in scan.checks))


class FakeScanner:
    def __init__(self, scan):
        self.result, self.calls = scan, []

    def scan(self, database, deadline_seconds=120):
        self.calls.append((database, deadline_seconds))
        return self.result


def execute(scan):
    return CheckIntegrity(FakeScanner(scan)).execute('PRIVATE-target.sqlite')


def corruption(owner='sqlite_physical', count=1, precision='exact'):
    code = 'sqlite_integrity_invalid' if owner == 'sqlite_physical' else 'sqlite_foreign_key_invalid'
    return IntegrityFinding(owner, code, 'corruption', count, count_precision=precision)


class CountedAssertions(unittest.TestCase):
    """Count explicit test assertion calls, including first failing assertions."""
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

    @classmethod
    def tearDownClass(cls):
        print(f'{cls.__name__}: executed assertions={cls.assertions}', file=sys.stderr)


class D3bCompletionTests(CountedAssertions):
    def test_full_exact_all_versions_clean_zero_final_d3_and_legacy_na(self):
        for version in range(6, 11):
            scan = completed_scan(version)
            report = execute(scan)
            with self.subTest(version=version):
                self.assertEqual((report.status, report.exit_code, report.complete,
                                  report.stop_reason, report.implemented_scope_complete),
                                 ('clean', 0, True, 'completed', True))
                self.assertEqual(report.checks, scan.checks)
                self.assertEqual((report.report_version, report.coverage_revision,
                                  report.required_scope_revision), (1, 'D3', 'P7-1'))
                self.assertEqual(tuple(c.check_id for c in report.checks), tuple(c[0] for c in CHECKS))
                self.assertEqual(tuple(c.check_id for c in report.checks if c.state == 'not_applicable'),
                                 tuple(name for name, unit, first in CHECKS if version < first))

    def test_fully_drained_physical_and_fk_corruption_complete_one_and_fixed_order(self):
        scan = changed(completed_scan(), 'sqlite_foreign_keys', count=2)
        findings = (corruption(), corruption('sqlite_foreign_keys', 2))
        report = execute(replace(scan, findings=tuple(reversed(findings))))
        self.assertEqual((report.status, report.exit_code, report.complete), ('corrupt', 1, True))
        self.assertEqual(report.findings, findings)
        self.assertEqual(report.checks, scan.checks)

    def test_physical_one_and_99_exact_and_fk_101_have_no_early_completion_loss(self):
        for physical_count in (1, 99):
            scan = changed(completed_scan(), 'sqlite_physical', count=physical_count)
            scan = changed(scan, 'sqlite_foreign_keys', count=101)
            findings = (corruption(count=physical_count), corruption('sqlite_foreign_keys', 101))
            report = execute(replace(scan, findings=findings))
            with self.subTest(physical_count=physical_count):
                self.assertEqual((report.status, report.exit_code, report.complete), ('corrupt', 1, True))
                self.assertEqual(report.findings, findings)
                self.assertEqual(report.checks, scan.checks)

    def test_physical_100_is_explicit_lower_bound_limit_not_complete_corruption(self):
        scan = changed(completed_scan(), 'sqlite_physical', state='interrupted', count=100,
                       count_precision='lower_bound')
        scan = changed(scan, 'sqlite_foreign_keys', state='blocked', count=None,
                       count_precision='unavailable')
        scan = changed(scan, 'resource_access', state='interrupted', count=0,
                       count_precision='lower_bound')
        findings = (corruption(count=100, precision='lower_bound'),
                    IntegrityFinding('resource_access', 'physical_limit_reached', 'operational', 1))
        scan = replace(scan, findings=findings, implemented_scope_complete=False, stop_reason='physical_limit')
        report = execute(scan)
        self.assertEqual((report.schema_version, report.stop_reason, report.checks, report.findings),
                         (10, 'physical_limit', scan.checks, findings))
        self.assertEqual((report.status, report.exit_code, report.complete), ('incomplete', 4, False))

    def test_corruption_then_late_operational_failure_retains_exact_evidence_and_priority(self):
        for reason, codes, exit_code in (
                ('read_error', ('read_failed',), 4),
                ('row_limit', ('row_limit_reached',), 4),
                ('utf8_limit', ('utf8_limit_reached',), 4),
                ('value_limit', ('value_limit_reached',), 4),
                ('deadline', ('deadline_exceeded',), 4),
                ('cleanup_error', ('read_failed', 'cleanup_failed'), 4),
                ('cancelled', ('cleanup_failed', 'cancelled'), 130)):
            scan = changed(completed_scan(), 'resource_access', state='interrupted', count=0,
                           count_precision='lower_bound')
            findings = (corruption(),) + tuple(IntegrityFinding('resource_access', code, 'operational', 1)
                                               for code in codes)
            scan = replace(scan, findings=findings, implemented_scope_complete=False, stop_reason=reason)
            report = execute(scan)
            with self.subTest(reason=reason):
                self.assertEqual((report.schema_version, report.stop_reason, report.exit_code, report.complete),
                                 (10, reason, exit_code, False))
                self.assertEqual(report.checks, scan.checks)
                self.assertEqual(set(report.findings), set(findings))


class D3bFakePortControls(CountedAssertions):
    def assert_sanitized(self, scan):
        report = execute(scan)
        self.assertEqual((report.schema_version, report.stop_reason, report.exit_code,
                          report.complete, report.implemented_scope_complete),
                         (None, 'read_error', 4, False, False))
        self.assertEqual(report.findings,
                         (IntegrityFinding('resource_access', 'read_failed', 'operational', 1),))
        self.assertNotIn('PRIVATE', repr(report))

    def test_invalid_owner_code_count_and_precision_are_sanitized_controls(self):
        scan = completed_scan()
        valid = corruption()
        for finding in (replace(valid, check_id='metadata'), replace(valid, code='PRIVATE SQL rowid=42'),
                        replace(valid, count_precision='lower_bound'), replace(valid, count=2),
                        replace(valid, severity='operational'), replace(valid, count=True),
                        replace(valid, count=0), replace(valid, count=-1),
                        replace(valid, count_unit='PRIVATE rows'), replace(valid, count=1.0),
                        replace(valid, count_precision='PRIVATE'),
                        corruption('sqlite_foreign_keys')):
            with self.subTest(finding=finding):
                self.assert_sanitized(replace(scan, findings=(finding,)))

    def test_completed_requires_all_exact_successful_cleanup_and_no_operational_contradictions_controls(self):
        scan = completed_scan()
        variants = [changed(scan, 'sqlite_physical', state='blocked', count=None, count_precision='unavailable'),
                    changed(scan, 'sqlite_foreign_keys', count_precision='lower_bound'),
                    changed(scan, 'resource_access', state='interrupted', count=0, count_precision='lower_bound'),
                    replace(scan, implemented_scope_complete=False), replace(scan, findings_truncated=True),
                    replace(scan, findings=(IntegrityFinding('resource_access', 'cleanup_failed', 'operational', 1),)),
                    replace(scan, supported=False), replace(scan, schema_version=None),
                    replace(scan, checks=scan.checks[:-1]),
                    replace(scan, checks=tuple(reversed(scan.checks))),
                    replace(scan, findings=(corruption(), corruption())),
                    changed(scan, 'sqlite_physical', count=0),
                    changed(scan, 'sqlite_physical', count=100),
                    changed(scan, 'resource_access', count=0),
                    changed(scan, 'compatibility', count=0)]
        for index, variant in enumerate(variants):
            with self.subTest(case=index): self.assert_sanitized(variant)

    def test_counterfeit_na_and_prerequisites_rejected_controls(self):
        for version in range(6, 11):
            scan = completed_scan(version)
            owners = ('schema', 'metadata', 'retained_stages', 'sqlite_physical', 'sqlite_foreign_keys')
            owners += (() if version == 6 else ('current_graph', 'historical_graph'))
            owners += (() if version < 9 else ('current_evidence', 'historical_evidence'))
            for owner in owners:
                with self.subTest(version=version, owner=owner):
                    self.assert_sanitized(changed(scan, owner, state='not_applicable', count=None,
                                                  count_precision='unavailable'))
            self.assert_sanitized(changed(scan, 'schema', state='blocked', count=None,
                                          count_precision='unavailable'))

    def test_no_completed_token_can_bypass_physical_limit_cause_controls(self):
        scan = replace(completed_scan(), findings=(IntegrityFinding(
            'resource_access', 'physical_limit_reached', 'operational', 1),))
        self.assert_sanitized(scan)
        self.assert_sanitized(replace(scan, stop_reason='physical_limit', implemented_scope_complete=False))

    def test_physical_cutoff_requires_exact_cause_and_lower_bound_controls(self):
        scan = changed(completed_scan(), 'sqlite_physical', state='interrupted', count=100,
                       count_precision='lower_bound')
        scan = changed(scan, 'sqlite_foreign_keys', state='blocked', count=None,
                       count_precision='unavailable')
        scan = changed(scan, 'resource_access', state='interrupted', count=0,
                       count_precision='lower_bound')
        findings = (corruption(count=100, precision='lower_bound'), IntegrityFinding(
            'resource_access', 'physical_limit_reached', 'operational', 1))
        scan = replace(scan, findings=findings, implemented_scope_complete=False,
                       stop_reason='physical_limit')
        variants = [changed(scan, 'sqlite_physical', count=99),
                    changed(scan, 'sqlite_physical', count=101),
                    replace(scan, findings=findings[:1]),
                    replace(scan, findings=findings[1:]),
                    replace(scan, stop_reason='completed'),
                    replace(scan, implemented_scope_complete=True),
                    replace(scan, findings=(replace(findings[0], count_precision='exact'), findings[1])),
                    replace(scan, findings=(findings[0], replace(findings[1], count_precision='exact')))]
        for index, variant in enumerate(variants):
            with self.subTest(case=index):
                self.assert_sanitized(variant)

    def test_exception_and_cancellation_are_sanitized_without_raw_port_errors_controls(self):
        class RaisingScanner:
            def __init__(self, error): self.error = error
            def scan(self, database, deadline_seconds): raise self.error
        for error, stop, code in ((ValueError('PRIVATE SQL rowid=42'), 'read_error', 4),
                                  (KeyboardInterrupt('PRIVATE'), 'cancelled', 130)):
            report = CheckIntegrity(RaisingScanner(error)).execute('PRIVATE-target.sqlite')
            self.assertEqual((report.stop_reason, report.exit_code, report.complete), (stop, code, False))
            self.assertNotIn('PRIVATE', repr(report))
