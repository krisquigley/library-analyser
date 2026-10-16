"""D3a inward port policy: selected completeness never means certification."""
from dataclasses import replace
import unittest

from music_analyzer.application.dto.integrity import IntegrityFinding
from music_analyzer.application.use_cases.check_integrity import CheckIntegrity
from tests.unit.application.test_integrity_d2_report import CHECKS, FakeScanner, selected_scan

CODES = {
    'metadata': ('metadata_json_invalid','metadata_contract_invalid','metadata_delivery_invalid'),
    'retained_stages': ('stage_json_invalid','stage_contract_invalid','stage_identity_invalid',
                        'stage_payload_oversized','stage_delivery_invalid'),
}


def d3a_scan(version=10,empty=False):
    scan=selected_scan(version)
    checks=tuple(replace(c,state='completed',count=0 if empty else (2 if c.check_id=='metadata' else 8),
                         count_precision='exact') if c.check_id in CODES else c for c in scan.checks)
    return replace(scan,checks=checks)


def execute(scan):
    return CheckIntegrity(FakeScanner(scan)).execute('public-d3a.sqlite')


def changed(scan,owner,**fields):
    return replace(scan,checks=tuple(replace(c,**fields) if c.check_id==owner else c for c in scan.checks))


class D3aReportControls(unittest.TestCase):
    def test_literal_scan_inventory_and_explicit_port_arguments(self):
        for version in range(6,11):
            scan=d3a_scan(version)
            self.assertEqual(tuple(c.check_id for c in scan.checks),tuple(c[0] for c in CHECKS))
            for c in scan.checks:
                if c.check_id in CODES: self.assertEqual((c.state,c.count_precision),('completed','exact'))
                if c.check_id.startswith('sqlite_'): self.assertEqual(c.state,'not_implemented')
            port=FakeScanner(scan); CheckIntegrity(port).execute('public-d3a.sqlite',2.5)
            self.assertEqual(port.calls,[('public-d3a.sqlite',2.5)])

    def test_counterfeit_full_completion_is_sanitized_not_certified(self):
        for scan in (replace(d3a_scan(),stop_reason='completed'),
                     changed(d3a_scan(),'sqlite_physical',state='completed',count=1,count_precision='exact')):
            report=execute(scan)
            self.assertEqual((report.schema_version,report.stop_reason,report.exit_code,report.complete),
                             (None,'read_error',4,False))


class D3aReportTests(unittest.TestCase):
    def test_all_supported_versions_selected_d3a_incomplete_four_with_physical_deferred(self):
        for version in range(6,11):
            scan=d3a_scan(version); report=execute(scan)
            for field,expected in (('schema_version',version),('checks',scan.checks),('findings',()),
                                   ('implemented_scope_complete',True),('stop_reason','scope_not_implemented'),
                                   ('status','incomplete'),('exit_code',4),('complete',False),('report_version',1),
                                   ('coverage_revision','D3'),('required_scope_revision','P7-1')):
                with self.subTest(version=version,field=field): self.assertEqual(getattr(report,field),expected)

    def test_empty_selected_phases_are_completed_exact_zero(self):
        scan=d3a_scan(empty=True); report=execute(scan)
        self.assertEqual(report.checks,scan.checks)
        self.assertTrue(report.implemented_scope_complete)

    def test_eight_codes_fixed_owner_order_and_one_occurrence_per_physical_row(self):
        literal=tuple(IntegrityFinding(owner,code,'corruption',1,count_precision='exact')
                      for owner,codes in CODES.items() for code in codes)
        report=execute(replace(d3a_scan(),findings=tuple(reversed(literal))))
        self.assertEqual(report.findings,literal)
        self.assertEqual((report.status,report.exit_code,report.complete),('incomplete',4,False))
        self.assertTrue(report.implemented_scope_complete,'observed corruption does not erase drained selected coverage')

    def test_interrupted_owner_counts_and_findings_are_lower_bound_including_zero(self):
        for owner in CODES:
            for count in (0,1):
                with self.subTest(owner=owner,count=count):
                    scan=changed(d3a_scan(),owner,state='interrupted',count=count,count_precision='lower_bound')
                    selected_order=('metadata','retained_stages','current_graph','historical_graph',
                                    'current_evidence','historical_evidence')
                    for later in selected_order[selected_order.index(owner)+1:]:
                        scan=changed(scan,later,state='blocked',count=None,count_precision='unavailable')
                    scan=changed(scan,'resource_access',state='interrupted',count=0,count_precision='lower_bound')
                    findings=(() if count==0 else (IntegrityFinding(owner,CODES[owner][0],'corruption',1),))
                    findings+=(IntegrityFinding('resource_access','read_failed','operational',1),)
                    scan=replace(scan,findings=findings,implemented_scope_complete=False,stop_reason='read_error')
                    report=execute(scan)
                    self.assertEqual((report.schema_version,report.checks,report.findings),(10,scan.checks,findings))
                    self.assertEqual((report.status,report.exit_code,report.complete),('incomplete',4,False))

    def test_reject_unknown_wrong_owner_precision_prerequisite_and_na_counterfeits(self):
        valid=d3a_scan()
        finding=IntegrityFinding('metadata','metadata_json_invalid','corruption',1,count_precision='exact')
        variants=[replace(valid,findings=(replace(finding,code='PRIVATE sql payload'),)),
                  replace(valid,findings=(replace(finding,check_id='retained_stages'),)),
                  replace(valid,findings=(replace(finding,count_precision='unavailable'),)),
                  changed(valid,'metadata',count_precision='lower_bound'),
                  changed(valid,'metadata',state='not_applicable',count=None,count_precision='unavailable'),
                  changed(valid,'schema',state='blocked',count=None,count_precision='unavailable'),
                  changed(valid,'compatibility',state='interrupted',count=0,count_precision='lower_bound')]
        interrupted=changed(valid,'metadata',state='interrupted',count=1,count_precision='lower_bound')
        interrupted=changed(interrupted,'resource_access',state='interrupted',count=0,count_precision='lower_bound')
        variants.append(replace(interrupted,implemented_scope_complete=False,stop_reason='read_error',
                                findings=(finding,IntegrityFinding('resource_access','read_failed','operational',1))))
        for index,scan in enumerate(variants):
            with self.subTest(case=index):
                report=execute(scan)
                self.assertEqual((report.schema_version,report.stop_reason,report.complete),(None,'read_error',False))
                self.assertEqual(report.findings,(IntegrityFinding('resource_access','read_failed','operational',1),))
                self.assertNotIn('PRIVATE',repr(report))


class D3aFindingCardinalityTests(unittest.TestCase):
    """Independent fake ports enforce per-code physical-row evidence bounds."""

    def scan_with_owner(self, owner, interrupted=False, rows=None):
        scan = d3a_scan()
        if not interrupted:
            return scan if rows is None else changed(scan, owner, count=rows)
        scan = changed(scan, owner, state='interrupted', count=rows,
                       count_precision='lower_bound')
        order = ('metadata', 'retained_stages', 'current_graph', 'historical_graph',
                 'current_evidence', 'historical_evidence')
        for later in order[order.index(owner) + 1:]:
            scan = changed(scan, later, state='blocked', count=None,
                           count_precision='unavailable')
        scan = changed(scan, 'resource_access', state='interrupted', count=0,
                       count_precision='lower_bound')
        return replace(scan, stop_reason='read_error', implemented_scope_complete=False,
                       findings=(IntegrityFinding('resource_access', 'read_failed', 'operational', 1),))

    def with_findings(self, scan, owner, count, precision):
        return replace(scan, findings=tuple(
            IntegrityFinding(owner, code, 'corruption', count, count_precision=precision)
            for code in CODES[owner]) + scan.findings)

    def assert_sanitized(self, scan):
        report = execute(scan)
        self.assertEqual((report.schema_version, report.stop_reason, report.exit_code,
                          report.complete, report.implemented_scope_complete),
                         (None, 'read_error', 4, False, False))
        self.assertEqual(report.findings,
                         (IntegrityFinding('resource_access', 'read_failed', 'operational', 1),))

    def test_completed_each_code_equality_underbound_and_zero_are_accepted_not_summed(self):
        for owner, rows in (('metadata', 2), ('retained_stages', 8)):
            for count in (0, 1, rows):
                with self.subTest(owner=owner, count=count):
                    scan = self.with_findings(self.scan_with_owner(owner), owner, count, 'exact')
                    report = execute(scan)
                    self.assertEqual((report.schema_version, report.checks, report.findings),
                                     (10, scan.checks, scan.findings))
                    self.assertTrue(report.implemented_scope_complete)
            scan = self.with_findings(self.scan_with_owner(owner, rows=0), owner, 0, 'exact')
            self.assertEqual(execute(scan).findings, scan.findings)

    def test_completed_lower_bound_and_over_observed_rows_are_sanitized_for_both_owners(self):
        for owner, rows in (('metadata', 2), ('retained_stages', 8)):
            for count, precision in ((1, 'lower_bound'), (rows + 1, 'exact')):
                with self.subTest(owner=owner, count=count, precision=precision):
                    self.assert_sanitized(self.with_findings(
                        self.scan_with_owner(owner), owner, count, precision))

    def test_interrupted_each_code_is_lower_bound_and_independently_row_bounded(self):
        for owner, rows in (('metadata', 2), ('retained_stages', 8)):
            for count in (0, 1, rows):
                with self.subTest(owner=owner, count=count):
                    scan = self.with_findings(self.scan_with_owner(owner, True, rows),
                                              owner, count, 'lower_bound')
                    report = execute(scan)
                    self.assertEqual((report.schema_version, report.checks, report.findings),
                                     (10, scan.checks, scan.findings))
                    self.assertFalse(report.implemented_scope_complete)
            scan = self.with_findings(self.scan_with_owner(owner, True, 0), owner, 0, 'lower_bound')
            self.assertEqual(execute(scan).findings, scan.findings)

    def test_interrupted_exact_or_over_observed_rows_are_sanitized_for_both_owners(self):
        for owner, rows in (('metadata', 2), ('retained_stages', 8)):
            for count, precision in ((1, 'exact'), (rows + 1, 'lower_bound')):
                with self.subTest(owner=owner, count=count, precision=precision):
                    self.assert_sanitized(self.with_findings(
                        self.scan_with_owner(owner, True, rows), owner, count, precision))

    def test_invalid_counts_remain_sanitized_for_completed_and_interrupted_owners(self):
        for owner in CODES:
            for interrupted in (False, True):
                for count in (-1, True, 1.0, None, 2_000_001):
                    with self.subTest(owner=owner, interrupted=interrupted, count=count):
                        scan = self.scan_with_owner(owner, interrupted, 2)
                        precision = 'lower_bound' if interrupted else 'exact'
                        self.assert_sanitized(self.with_findings(scan, owner, count, precision))
                        self.assert_sanitized(changed(scan, owner, count=count))
