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
                                   ('coverage_revision','D3a'),('required_scope_revision','P7-1')):
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
