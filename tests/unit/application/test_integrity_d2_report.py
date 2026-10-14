"""D2a report contract through an inward fake port; no SQLite or framework."""
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
GRAPH_CODES = ('graph_lifecycle_invalid', 'graph_counts_invalid', 'graph_pointer_invalid',
               'graph_mirror_invalid', 'graph_edge_invalid')
OWNERS = ('current_graph', 'historical_graph')


def selected_scan(version, empty=False):
    """Literal approved semantic counts, not query-fetch or mirror-lookup counts."""
    checks = []
    graph_counts = (2, 4) if version == 7 else (3, 8)
    for name, unit, first_version in CHECKS:
        if name in ('compatibility', 'schema', 'core_rows', 'resource_access'):
            state, count, precision = 'completed', 1, 'exact'
        elif name in OWNERS and version >= 7:
            state, count, precision = 'completed', 0 if empty else graph_counts[OWNERS.index(name)], 'exact'
        else:
            state = 'not_applicable' if version < first_version else 'not_implemented'
            count, precision = None, 'unavailable'
        checks.append(IntegrityCheck(name, name, state, count, unit, precision))
    return IntegrityScan(version, tuple(checks), implemented_scope_complete=True)


class FakeScanner:
    def __init__(self, scan):
        self.result = scan
        self.calls = []

    def scan(self, database, deadline_seconds=120):
        self.calls.append((database, deadline_seconds))
        return self.result


def execute(scan):
    return CheckIntegrity(FakeScanner(scan)).execute('public-graph.sqlite')


class IntegrityD2Report(unittest.TestCase):
    def test_selected_graph_states_counts_fixed_inventory_and_noncertification(self):
        for version in range(6, 11):
            scan = selected_scan(version)
            report = execute(scan)
            for field, expected in (
                    ('schema_version', version), ('checks', scan.checks), ('findings', ()),
                    ('implemented_scope_complete', True), ('stop_reason', 'scope_not_implemented'),
                    ('status', 'incomplete'), ('exit_code', 4), ('complete', False),
                    ('report_version', 1), ('coverage_revision', 'D2a'),
                    ('required_scope_revision', 'P7-1'),
                    ('supported_schema_versions', (6, 7, 8, 9, 10))):
                with self.subTest(version=version, field=field):
                    self.assertEqual(getattr(report, field), expected,
                                     'selected D2a graph coverage is not full P7 certification')
            with self.subTest(version=version, inventory=True):
                self.assertEqual(tuple(c.check_id for c in report.checks), tuple(c[0] for c in CHECKS))

    def test_empty_selected_graphs_are_completed_zero_exact_not_unavailable(self):
        for version in range(7, 11):
            report = execute(selected_scan(version, empty=True))
            for owner in OWNERS:
                with self.subTest(version=version, owner=owner):
                    check = next(c for c in report.checks if c.check_id == owner)
                    self.assertEqual((check.state, check.count, check.count_unit, check.count_precision),
                                     ('completed', 0, 'rows', 'exact'))

    def test_all_five_reserved_codes_are_preserved_for_each_graph_owner(self):
        for owner in OWNERS:
            for code in GRAPH_CODES:
                finding = IntegrityFinding(owner, code, 'corruption', 2, count_precision='exact')
                report = execute(replace(selected_scan(10), findings=(finding,)))
                with self.subTest(owner=owner, code=code):
                    self.assertEqual(report.findings, (finding,),
                                     'approved graph corruption codes must survive the inward boundary')
                with self.subTest(owner=owner, code=code, selected=True):
                    self.assertTrue(report.implemented_scope_complete,
                                    'exhausted corruption is distinct from interrupted coverage')
                with self.subTest(owner=owner, code=code, certification=True):
                    self.assertEqual((report.status, report.exit_code, report.complete), ('incomplete', 4, False))

    def test_findings_order_is_fixed_owner_then_approved_code_order(self):
        findings = tuple(IntegrityFinding(owner, code, 'corruption', 1, count_precision='exact')
                         for owner in OWNERS for code in GRAPH_CODES)
        report = execute(replace(selected_scan(8), findings=tuple(reversed(findings))))
        self.assertEqual(report.findings, findings, 'port order must not change the public finding order')

    def test_interrupted_graph_retains_lower_bound_and_read_failed_without_certification(self):
        for owner in OWNERS:
            scan = selected_scan(10)
            checks = tuple(replace(c, state='interrupted', count=0, count_precision='lower_bound')
                           if c.check_id == 'resource_access' else
                           replace(c, state='interrupted', count=1, count_precision='lower_bound')
                           if c.check_id == owner else c for c in scan.checks)
            findings = (IntegrityFinding(owner, 'graph_edge_invalid', 'corruption', 1),
                        IntegrityFinding('resource_access', 'read_failed', 'operational', 1))
            scan = replace(scan, checks=checks, findings=findings,
                           implemented_scope_complete=False, stop_reason='read_error')
            report = execute(scan)
            for field, expected in (('schema_version', 10), ('checks', checks), ('findings', findings),
                                    ('implemented_scope_complete', False), ('stop_reason', 'read_error'),
                                    ('status', 'incomplete'), ('exit_code', 4), ('complete', False)):
                with self.subTest(owner=owner, field=field):
                    self.assertEqual(getattr(report, field), expected,
                                     'late graph read failure retains recognized lower-bound evidence')


class IntegrityD2ReportControls(unittest.TestCase):
    def test_fake_scan_inventory_has_literal_approved_shape(self):
        for version in range(6, 11):
            scan = selected_scan(version)
            self.assertEqual(tuple(c.check_id for c in scan.checks), tuple(c[0] for c in CHECKS))
            self.assertTrue(scan.implemented_scope_complete)
            graph = tuple((c.state, c.count, c.count_precision) for c in scan.checks if c.check_id in OWNERS)
            expected = (('not_applicable', None, 'unavailable'),) * 2 if version == 6 else tuple(
                ('completed', count, 'exact') for count in ((2, 4) if version == 7 else (3, 8)))
            self.assertEqual(graph, expected)
            for c in scan.checks:
                if c.check_id in ('current_evidence', 'historical_evidence'):
                    self.assertEqual(c.state, 'not_applicable' if version < 9 else 'not_implemented')

    def test_injected_port_forwards_only_explicit_target_and_deadline(self):
        port = FakeScanner(selected_scan(6))
        CheckIntegrity(port).execute('public-graph.sqlite', 2.5)
        self.assertEqual(port.calls, [('public-graph.sqlite', 2.5)])

    def test_unknown_codes_units_and_precision_use_sanitized_fallback(self):
        valid = selected_scan(10)
        finding = IntegrityFinding('historical_graph', 'graph_edge_invalid', 'corruption', 1,
                                   count_precision='exact')
        malformed = [
            replace(valid, findings=(replace(finding, code='PRIVATE unknown SQL'),)),
            replace(valid, findings=(replace(finding, count_unit='PRIVATE units'),)),
            replace(valid, findings=(replace(finding, count_precision='PRIVATE precision'),)),
            replace(valid, findings=(replace(finding, severity='PRIVATE severity'),)),
        ]
        for field, value in (('count_unit', 'PRIVATE units'), ('count_precision', 'PRIVATE precision')):
            malformed.append(replace(valid, checks=tuple(
                replace(c, **{field: value}) if c.check_id == 'current_graph' else c for c in valid.checks)))
        for index, scan in enumerate(malformed):
            with self.subTest(case=index):
                report = CheckIntegrity(FakeScanner(scan)).execute('PRIVATE TARGET.sqlite')
                self.assertEqual((report.schema_version, report.stop_reason, report.status, report.exit_code,
                                  report.implemented_scope_complete, report.complete),
                                 (None, 'read_error', 'incomplete', 4, False, False))
                self.assertEqual(report.findings,
                                 (IntegrityFinding('resource_access', 'read_failed', 'operational', 1),))
                self.assertNotIn('PRIVATE', repr(report))
