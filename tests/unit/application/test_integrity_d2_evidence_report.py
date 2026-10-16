"""Approved atomic full-D2 policy through a pure inward fake scanner port."""
from dataclasses import replace
import unittest

from music_analyzer.application.dto.integrity import IntegrityCheck, IntegrityFinding, IntegrityScan
from music_analyzer.application.use_cases.check_integrity import CheckIntegrity

CHECKS = (
    ('compatibility', 'databases', 6), ('schema', 'schema_descriptors', 6),
    ('core_rows', 'rows', 6), ('metadata', 'rows', 6), ('retained_stages', 'rows', 6),
    ('current_graph', 'rows', 7), ('historical_graph', 'rows', 7),
    ('current_evidence', 'rows', 9), ('historical_evidence', 'rows', 9),
    ('sqlite_physical', 'physical_records', 6), ('sqlite_foreign_keys', 'foreign_key_records', 6),
    ('resource_access', 'databases', 6),
)
OWNERS = ('current_evidence', 'historical_evidence')
CODES = ('evidence_envelope_invalid', 'evidence_link_invalid', 'evidence_json_invalid',
         'evidence_contract_invalid', 'evidence_feature_invalid', 'evidence_summary_invalid',
         'evidence_fingerprint_invalid', 'evidence_delivery_invalid', 'evidence_payload_oversized')


def evidence_scan(version=10, empty=False):
    checks = []
    for name, unit, first in CHECKS:
        if name in ('compatibility', 'schema', 'core_rows', 'metadata', 'retained_stages', 'resource_access'):
            state, count, precision = 'completed', 1, 'exact'
        elif name in ('current_graph', 'historical_graph') and version >= 7:
            graph_counts = (2, 4) if version == 7 else (3, 8)
            state, count, precision = 'completed', 0 if empty else graph_counts[('current_graph', 'historical_graph').index(name)], 'exact'
        elif name in OWNERS and version >= 9:
            state, count, precision = 'completed', 0 if empty else 2, 'exact'
        else:
            state, count, precision = ('not_applicable' if version < first else 'not_implemented'), None, 'unavailable'
        checks.append(IntegrityCheck(name, name, state, count, unit, precision))
    return IntegrityScan(version, tuple(checks), implemented_scope_complete=True)


class FakeScanner:
    def __init__(self, scan):
        self.result, self.calls = scan, []

    def scan(self, database, deadline_seconds=120):
        self.calls.append((database, deadline_seconds))
        return self.result


def execute(scan):
    return CheckIntegrity(FakeScanner(scan)).execute('public-evidence.sqlite')


class IntegrityD2EvidenceReportControls(unittest.TestCase):
    def test_independent_inventory_semantic_counts_and_empty_legacy(self):
        for version in range(6, 11):
            for empty in (False, True):
                with self.subTest(version=version, empty=empty):
                    scan = evidence_scan(version, empty)
                    self.assertEqual(tuple(c.check_id for c in scan.checks), tuple(c[0] for c in CHECKS))
                    evidence = tuple((c.state, c.count, c.count_precision) for c in scan.checks if c.check_id in OWNERS)
                    expected = (('not_applicable', None, 'unavailable'),) * 2 if version < 9 else (('completed', 0 if empty else 2, 'exact'),) * 2
                    self.assertEqual(evidence, expected)

    def test_explicit_port_target_deadline_and_sanitized_unknown_code(self):
        # Legacy6 DTO is already baseline-supported: positive forwarding control
        # does not smuggle the desired new capability into an existing control.
        port = FakeScanner(evidence_scan(6))
        CheckIntegrity(port).execute('public-evidence.sqlite', 2.5)
        self.assertEqual(port.calls, [('public-evidence.sqlite', 2.5)])
        finding = IntegrityFinding('historical_evidence', 'PRIVATE SQL unknown', 'corruption', 1)
        report = execute(replace(evidence_scan(), findings=(finding,)))
        self.assertEqual((report.stop_reason, report.exit_code, report.complete), ('read_error', 4, False))
        self.assertNotIn('PRIVATE', repr(report))

    def test_invalid_evidence_port_metadata_is_sanitized_without_certification(self):
        scan = evidence_scan()
        cases = []
        for field, value in (('count', -1), ('count', True), ('count_unit', 'PRIVATE units'), ('state', 'PRIVATE state'), ('count_precision', 'PRIVATE precision')):
            cases.append(replace(scan, checks=tuple(replace(c, **{field: value}) if c.check_id == OWNERS[0] else c for c in scan.checks)))
        for field, value in (('severity', 'operational'), ('count_unit', 'PRIVATE unit'), ('count_precision', 'PRIVATE precision'), ('code', 'PRIVATE code'), ('check_id', 'metadata')):
            f = IntegrityFinding(OWNERS[0], CODES[0], 'corruption', 1, count_precision='exact')
            cases.append(replace(scan, findings=(replace(f, **{field: value}),)))
        # A schema-blocked port cannot assert evidence applicability or exhaustion.
        cases.append(replace(scan, checks=tuple(replace(c, state='blocked', count=None, count_precision='unavailable') if c.check_id == 'schema' else c for c in scan.checks), stop_reason='schema_blocked'))
        for index, malformed in enumerate(cases):
            with self.subTest(case=index):
                report = execute(malformed)
                self.assertEqual(report.schema_version, None)
                self.assertFalse(report.implemented_scope_complete)
                self.assertFalse(report.complete)
                self.assertNotIn('PRIVATE', repr(report))


class IntegrityD2EvidenceReport(unittest.TestCase):
    def test_atomic_d2_fixed_inventory_noncertificate_and_applicability(self):
        for version in range(6, 11):
            with self.subTest(version=version):
                scan = evidence_scan(version)
                report = execute(scan)
                self.assertEqual(report.coverage_revision, 'D3')
                self.assertEqual(report.checks, scan.checks)
                self.assertEqual((report.report_version, report.required_scope_revision), (1, 'P7-1'))
                self.assertEqual((report.status, report.exit_code, report.complete), ('incomplete', 4, False))
                self.assertTrue(report.implemented_scope_complete)
                self.assertEqual(report.supported_schema_versions, (6, 7, 8, 9, 10))
                for c in report.checks:
                    if c.check_id in ('sqlite_physical', 'sqlite_foreign_keys'):
                        self.assertEqual(c.state, 'not_implemented')

    def test_empty_evidence_completed_zero_exact_is_not_unavailable(self):
        scan = evidence_scan(empty=True)
        report = execute(scan)
        for owner in OWNERS:
            with self.subTest(owner=owner):
                c = next(c for c in report.checks if c.check_id == owner)
                self.assertEqual((c.state, c.count, c.count_precision), ('completed', 0, 'exact'))
        self.assertTrue(report.implemented_scope_complete)

    def test_all_nine_codes_both_owners_fixed_order_and_exhausted_corruption(self):
        for owner in OWNERS:
            for code in CODES:
                with self.subTest(owner=owner, code=code):
                    finding = IntegrityFinding(owner, code, 'corruption', 1, count_precision='exact')
                    report = execute(replace(evidence_scan(), findings=(finding,)))
                    self.assertEqual(report.findings, (finding,))
                    self.assertTrue(report.implemented_scope_complete)
                    self.assertEqual((report.exit_code, report.complete), (4, False))
        expected = tuple(IntegrityFinding(owner, code, 'corruption', 1, count_precision='exact') for owner in OWNERS for code in CODES)
        self.assertEqual(execute(replace(evidence_scan(), findings=tuple(reversed(expected)))).findings, expected)

    def test_interrupted_phase_lower_bound_prior_exact_and_future_blocked(self):
        for owner in OWNERS:
            with self.subTest(owner=owner):
                scan = evidence_scan()
                checks = tuple(replace(c, state='interrupted', count=0, count_precision='lower_bound') if c.check_id == 'resource_access' else
                               replace(c, state='interrupted', count=1, count_precision='lower_bound') if c.check_id == owner else
                               replace(c, state='blocked', count=None, count_precision='unavailable') if owner == OWNERS[0] and c.check_id == OWNERS[1] else c for c in scan.checks)
                found = (IntegrityFinding(owner, 'evidence_json_invalid', 'corruption', 1, count_precision='lower_bound'),
                         IntegrityFinding('resource_access', 'read_failed', 'operational', 1, count_precision='lower_bound'))
                report = execute(replace(scan, checks=checks, findings=found, implemented_scope_complete=False, stop_reason='read_error'))
                self.assertEqual(report.checks, checks)
                self.assertEqual(report.findings, found)
                self.assertEqual((report.schema_version, report.stop_reason, report.exit_code), (10, 'read_error', 4))
                self.assertFalse(report.implemented_scope_complete)
                self.assertFalse(report.complete)

    def test_partial_evidence_cannot_silently_complete_selected_scope(self):
        scan = evidence_scan()
        checks = tuple(replace(c, state='not_implemented', count=None, count_precision='unavailable') if c.check_id == OWNERS[1] else c for c in scan.checks)
        report = execute(replace(scan, checks=checks))
        self.assertFalse(report.implemented_scope_complete)
        self.assertEqual(report.coverage_revision, 'D3')
        self.assertEqual((report.exit_code, report.complete), (4, False))

