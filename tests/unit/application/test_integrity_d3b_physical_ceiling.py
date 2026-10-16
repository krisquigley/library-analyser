"""Physical delivery ceiling at the inward output-port boundary; no SQLite."""
from dataclasses import replace
import unittest

from music_analyzer.application.dto.integrity import IntegrityCheck, IntegrityFinding, IntegrityScan
from music_analyzer.application.use_cases.check_integrity import CheckIntegrity


CHECKS = (
    ('compatibility', 'databases'), ('schema', 'schema_descriptors'),
    ('core_rows', 'rows'), ('metadata', 'rows'), ('retained_stages', 'rows'),
    ('current_graph', 'rows'), ('historical_graph', 'rows'),
    ('current_evidence', 'rows'), ('historical_evidence', 'rows'),
    ('sqlite_physical', 'physical_records'),
    ('sqlite_foreign_keys', 'foreign_key_records'), ('resource_access', 'databases'),
)
ORDINARY_STOPS = (
    ('read_error', 'read_failed'), ('deadline', 'deadline_exceeded'),
    ('row_limit', 'row_limit_reached'), ('utf8_limit', 'utf8_limit_reached'),
    ('value_limit', 'value_limit_reached'), ('finding_limit', 'finding_limit_reached'),
    ('cleanup_error', 'cleanup_failed'), ('cancelled', 'cancelled'),
)


def completed_scan():
    checks = tuple(IntegrityCheck(name, name, 'completed',
                                  1 if name in ('compatibility', 'resource_access', 'sqlite_physical') else 0,
                                  unit, 'exact') for name, unit in CHECKS)
    return IntegrityScan(10, checks, implemented_scope_complete=True, stop_reason='completed')


def change(scan, owner, **fields):
    return replace(scan, checks=tuple(replace(item, **fields) if item.check_id == owner else item
                                     for item in scan.checks))


def physical_finding(count, precision='lower_bound'):
    return IntegrityFinding('sqlite_physical', 'sqlite_integrity_invalid', 'corruption',
                            count, count_precision=precision)


def operational(code):
    return IntegrityFinding('resource_access', code, 'operational', 1)


def interrupted_scan(count, stop='read_error', code='read_failed', cutoff=False):
    scan = change(completed_scan(), 'sqlite_physical', state='interrupted', count=count,
                  count_precision='lower_bound')
    scan = change(scan, 'sqlite_foreign_keys', state='blocked', count=None,
                  count_precision='unavailable')
    scan = change(scan, 'resource_access', state='interrupted', count=0,
                  count_precision='lower_bound')
    causes = (operational('physical_limit_reached'),) if cutoff else ()
    if code != 'physical_limit_reached':
        causes += (operational(code),)
    return replace(scan, findings=(physical_finding(count),) + causes,
                   implemented_scope_complete=False, stop_reason=stop)


def execute(scan):
    class FakeScanner:
        def scan(self, database, deadline_seconds):
            return scan
    return CheckIntegrity(FakeScanner()).execute('PRIVATE-target.sqlite')


class PhysicalCeilingTests(unittest.TestCase):
    def assert_sanitized(self, scan):
        report = execute(scan)
        self.assertEqual((report.schema_version, report.stop_reason, report.exit_code,
                          report.complete, report.implemented_scope_complete),
                         (None, 'read_error', 4, False, False))
        self.assertEqual(report.findings, (operational('read_failed'),))
        self.assertTrue(all(item.state == ('interrupted' if item.check_id == 'resource_access'
                                           else 'blocked') for item in report.checks))
        self.assertNotIn('PRIVATE', repr(report))

    def assert_retained(self, scan):
        report = execute(scan)
        self.assertEqual(report.schema_version, 10)
        self.assertEqual(report.checks, scan.checks)
        self.assertEqual(set(report.findings), set(scan.findings))
        self.assertEqual(report.stop_reason, scan.stop_reason)
        self.assertEqual(report.exit_code, 130 if scan.stop_reason == 'cancelled' else 4)
        self.assertFalse(report.complete)
        self.assertFalse(report.implemented_scope_complete)

    def test_interrupted_101_read_error_is_sanitized_not_retained(self):
        self.assert_sanitized(interrupted_scan(101))

    def test_over_100_is_sanitized_under_every_accepted_stop(self):
        stops = ORDINARY_STOPS + (
            ('completed', 'read_failed'), ('physical_limit', 'physical_limit_reached'),
            ('scope_not_implemented', 'read_failed'),
            ('unsupported_database', 'read_failed'),
            ('unreadable_database', 'initial_access_failed'),
            ('schema_blocked', 'read_failed'),
        )
        for count in (101, 2_000_000):
            for stop, code in stops:
                with self.subTest(count=count, stop=stop):
                    self.assert_sanitized(interrupted_scan(count, stop, code,
                                                           cutoff=stop == 'physical_limit'))

    def test_100_without_cutoff_marker_retains_ordinary_errors_and_cancel(self):
        for stop, code in ORDINARY_STOPS:
            with self.subTest(stop=stop):
                self.assert_retained(interrupted_scan(100, stop, code))

    def test_cutoff_100_retains_required_marker_and_cleanup_cancel_precedence(self):
        for stop, code in (('physical_limit', 'physical_limit_reached'),
                           ('cleanup_error', 'cleanup_failed'), ('cancelled', 'cancelled')):
            with self.subTest(stop=stop):
                self.assert_retained(interrupted_scan(100, stop, code, cutoff=True))

    def test_cutoff_requires_exact_terminal_count_precision_cause_and_blocked_fk(self):
        scan = interrupted_scan(100, 'physical_limit', 'physical_limit_reached', cutoff=True)
        variants = (
            interrupted_scan(99, 'physical_limit', 'physical_limit_reached', cutoff=True),
            change(scan, 'sqlite_physical', count_precision='exact'),
            replace(scan, findings=(physical_finding(100, 'exact'), scan.findings[1])),
            replace(scan, findings=scan.findings[:1]),
            change(scan, 'sqlite_foreign_keys', state='completed', count=0, count_precision='exact'),
            replace(scan, stop_reason='completed', implemented_scope_complete=True),
        )
        for index, variant in enumerate(variants):
            with self.subTest(case=index):
                self.assert_sanitized(variant)

    def test_completed_100_exact_is_not_terminal_eof_but_99_exact_is(self):
        for count in (99, 100, 101):
            scan = change(completed_scan(), 'sqlite_physical', count=count)
            scan = replace(scan, findings=(physical_finding(count, 'exact'),))
            with self.subTest(count=count):
                if count >= 100:
                    self.assert_sanitized(scan)
                else:
                    report = execute(scan)
                    self.assertEqual((report.schema_version, report.status, report.exit_code,
                                      report.complete), (10, 'corrupt', 1, True))
                    self.assertEqual(report.checks, scan.checks)
                    self.assertEqual(report.findings, scan.findings)

    def test_physical_ceiling_does_not_limit_completed_foreign_key_count(self):
        scan = change(completed_scan(), 'sqlite_foreign_keys', count=101)
        finding = IntegrityFinding('sqlite_foreign_keys', 'sqlite_foreign_key_invalid',
                                   'corruption', 101, count_precision='exact')
        report = execute(replace(scan, findings=(finding,)))
        self.assertEqual((report.schema_version, report.exit_code, report.complete), (10, 1, True))
        self.assertEqual(report.findings, (finding,))
