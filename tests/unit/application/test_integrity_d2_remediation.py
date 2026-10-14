"""Graph prerequisites at the inward output port; no persistence dependencies."""
from dataclasses import replace
import unittest

from music_analyzer.application.dto.integrity import IntegrityFinding
from music_analyzer.application.use_cases.check_integrity import CheckIntegrity
from tests.unit.application.test_integrity_d1_report import stopped_scan
from tests.unit.application.test_integrity_d2_report import (
    FakeScanner, GRAPH_CODES, OWNERS, selected_scan,
)


def change_checks(scan, names, state):
    count = 0 if state in ('completed', 'interrupted') else None
    precision = {'completed': 'exact', 'interrupted': 'lower_bound'}.get(state, 'unavailable')
    return replace(scan, checks=tuple(
        replace(c, state=state, count=count, count_precision=precision)
        if c.check_id in names else c for c in scan.checks))


def schema_stop(version, schema_state='completed', cancelled=False):
    scan = change_checks(selected_scan(version), ('core_rows',), 'blocked')
    if version >= 7:
        scan = change_checks(scan, OWNERS, 'blocked')
    scan = change_checks(scan, ('schema',), schema_state)
    findings = (IntegrityFinding('schema', 'schema_object_set_mismatch', 'corruption', 1,
                                 count_precision='exact'),)
    stop = 'schema_blocked'
    if schema_state == 'interrupted' or cancelled:
        scan = change_checks(scan, ('resource_access',), 'interrupted')
        stop = 'cancelled' if cancelled else 'read_error'
        findings = (() if schema_state == 'interrupted' else findings) + (
            IntegrityFinding('resource_access', 'cancelled' if cancelled else 'read_failed',
                             'operational', 1),)
    return replace(scan, findings=findings, stop_reason=stop, implemented_scope_complete=False)


class IntegrityD2PrerequisiteRemediation(unittest.TestCase):
    def report(self, scan):
        return CheckIntegrity(FakeScanner(scan)).execute('PRIVATE TARGET.sqlite')

    def assert_preserved(self, scan):
        report = self.report(scan)
        self.assertEqual((report.schema_version, report.checks, report.findings,
                          report.stop_reason, report.implemented_scope_complete),
                         (scan.schema_version, scan.checks, scan.findings,
                          scan.stop_reason, scan.implemented_scope_complete))
        self.assertFalse(report.complete)
        expected_exit = 130 if scan.stop_reason == 'cancelled' else (
            3 if scan.stop_reason == 'unsupported_database' else 4)
        self.assertEqual(report.exit_code, expected_exit)

    def assert_sanitized(self, scan):
        report = self.report(scan)
        self.assertEqual((report.schema_version, report.stop_reason, report.status,
                          report.exit_code, report.implemented_scope_complete, report.complete),
                         (None, 'read_error', 'incomplete', 4, False, False))
        self.assertEqual(report.findings, (
            IntegrityFinding('resource_access', 'read_failed', 'operational', 1),))
        for check in report.checks:
            self.assertEqual((check.state, check.count, check.count_precision),
                             ('interrupted', 0, 'lower_bound') if check.check_id == 'resource_access'
                             else ('blocked', None, 'unavailable'))
        self.assertNotIn('PRIVATE', repr(report))

    def test_unrecognized_graph_work_cannot_complete_or_start(self):
        for stop in ('unsupported_database', 'read_error', 'cancelled'):
            scan = stopped_scan(stop)
            self.assert_preserved(scan)
            for owner in OWNERS:
                for state in ('completed', 'interrupted'):
                    with self.subTest(stop=stop, owner=owner, state=state):
                        self.assert_sanitized(change_checks(scan, (owner,), state))

    def test_schema_prerequisite_failure_cannot_complete_or_start_graph_work(self):
        for version in range(7, 11):
            for schema_state in ('completed', 'blocked', 'interrupted'):
                scan = schema_stop(version, schema_state)
                self.assert_preserved(scan)
                for owner in OWNERS:
                    for state in ('completed', 'interrupted'):
                        with self.subTest(version=version, schema=schema_state,
                                          owner=owner, state=state):
                            self.assert_sanitized(change_checks(scan, (owner,), state))

    def test_blocked_graph_findings_cannot_bypass_unknown_or_failed_prerequisites(self):
        for scan in (stopped_scan('read_error'), schema_stop(10)):
            with self.subTest(version=scan.schema_version, stop=scan.stop_reason):
                owner = next(c for c in scan.checks if c.check_id == 'historical_graph')
                self.assertEqual((owner.state, owner.count, owner.count_precision),
                                 ('blocked', None, 'unavailable'))
                malformed = replace(scan, findings=scan.findings + (IntegrityFinding(
                    'historical_graph', 'graph_edge_invalid', 'corruption', 1,
                    count_precision='exact'),))
                self.assert_sanitized(malformed)

    def test_blocked_owner_cannot_carry_graph_findings_after_successful_schema(self):
        scan = change_checks(selected_scan(10), ('historical_graph', 'resource_access'), 'interrupted')
        scan = change_checks(scan, ('historical_graph',), 'blocked')
        scan = replace(scan, stop_reason='read_error', implemented_scope_complete=False,
                       findings=(IntegrityFinding('resource_access', 'read_failed', 'operational', 1),))
        self.assert_preserved(scan)
        self.assert_sanitized(replace(scan, findings=scan.findings + (IntegrityFinding(
            'historical_graph', 'graph_edge_invalid', 'corruption', 1,
            count_precision='exact'),)))

    def test_v6_not_applicable_graphs_cannot_carry_any_graph_corruption(self):
        scan = selected_scan(6)
        self.assert_preserved(scan)
        for owner in OWNERS:
            for code in GRAPH_CODES:
                with self.subTest(owner=owner, code=code):
                    self.assert_sanitized(replace(scan, findings=(IntegrityFinding(
                        owner, code, 'corruption', 1, count_precision='exact'),)))

    def test_genuine_v6_not_applicable_survives_schema_block_and_cancellation(self):
        for cancelled in (False, True):
            with self.subTest(cancelled=cancelled):
                self.assert_preserved(schema_stop(6, cancelled=cancelled))

    def test_applicable_blocked_graphs_preserve_schema_corruption_and_cancel_exit(self):
        for version in range(7, 11):
            with self.subTest(version=version):
                self.assert_preserved(schema_stop(version, cancelled=True))

    def test_recognized_healthy_schema_allows_exact_and_interrupted_graph_evidence(self):
        for version in range(7, 11):
            self.assert_preserved(selected_scan(version))
            for owner in OWNERS:
                with self.subTest(version=version, owner=owner, state='completed'):
                    self.assert_preserved(replace(selected_scan(version), findings=(IntegrityFinding(
                        owner, 'graph_edge_invalid', 'corruption', 1, count_precision='exact'),)))
                scan = change_checks(selected_scan(version), (owner, 'resource_access'), 'interrupted')
                scan = replace(scan, stop_reason='read_error', implemented_scope_complete=False,
                               findings=(IntegrityFinding(owner, 'graph_edge_invalid', 'corruption', 1),
                                         IntegrityFinding('resource_access', 'read_failed', 'operational', 1)))
                with self.subTest(version=version, owner=owner):
                    self.assert_preserved(scan)
