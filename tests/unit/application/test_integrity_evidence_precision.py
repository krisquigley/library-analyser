"""Evidence owner precision contract through the public application boundary."""
from dataclasses import replace
import unittest

from music_analyzer.application.dto.integrity import IntegrityFinding
from tests.unit.application.test_integrity_d2_evidence_report import (
    CODES, OWNERS, evidence_scan, execute,
)


def interrupted_scan(owner, finding):
    scan = evidence_scan()
    checks = tuple(
        replace(c, state='interrupted', count=0, count_precision='lower_bound')
        if c.check_id == 'resource_access' else
        replace(c, state='interrupted', count=1, count_precision='lower_bound')
        if c.check_id == owner else
        replace(c, state='blocked', count=None, count_precision='unavailable')
        if owner == 'current_evidence' and c.check_id == 'historical_evidence' else c
        for c in scan.checks
    )
    operational = IntegrityFinding('resource_access', 'read_failed', 'operational', 1,
                                   count_precision='lower_bound')
    return replace(scan, checks=checks, findings=(finding, operational),
                   implemented_scope_complete=False, stop_reason='read_error')


class IntegrityEvidencePrecision(unittest.TestCase):
    def test_interrupted_exact_findings_are_sanitized_for_all_codes_and_owners(self):
        for owner in OWNERS:
            for code in CODES:
                with self.subTest(owner=owner, code=code):
                    finding = IntegrityFinding(owner, code, 'corruption', 1,
                                               count_precision='exact')
                    report = execute(interrupted_scan(owner, finding))
                    self.assertIsNone(report.schema_version)
                    self.assertEqual((report.stop_reason, report.exit_code), ('read_error', 4))
                    self.assertFalse(report.implemented_scope_complete)
                    self.assertFalse(report.complete)
                    self.assertEqual(report.findings, (
                        IntegrityFinding('resource_access', 'read_failed', 'operational', 1),))
                    self.assertTrue(all(c.state == ('interrupted' if c.check_id == 'resource_access'
                                                   else 'blocked') for c in report.checks))

    def test_interrupted_lower_bound_findings_remain_accepted_for_all_codes_and_owners(self):
        for owner in OWNERS:
            for code in CODES:
                with self.subTest(owner=owner, code=code):
                    finding = IntegrityFinding(owner, code, 'corruption', 1,
                                               count_precision='lower_bound')
                    scan = interrupted_scan(owner, finding)
                    report = execute(scan)
                    self.assertEqual(report.schema_version, 10)
                    self.assertEqual(report.checks, scan.checks)
                    self.assertEqual(report.findings, scan.findings)
                    self.assertEqual((report.stop_reason, report.exit_code), ('read_error', 4))
                    self.assertFalse(report.implemented_scope_complete)
                    self.assertFalse(report.complete)

    def test_completed_exact_findings_remain_accepted_for_all_codes_and_owners(self):
        for owner in OWNERS:
            for code in CODES:
                with self.subTest(owner=owner, code=code):
                    finding = IntegrityFinding(owner, code, 'corruption', 1,
                                               count_precision='exact')
                    scan = replace(evidence_scan(), findings=(finding,))
                    report = execute(scan)
                    self.assertEqual(report.schema_version, 10)
                    self.assertEqual(report.checks, scan.checks)
                    self.assertEqual(report.findings, (finding,))
                    self.assertEqual((report.stop_reason, report.exit_code), ('scope_not_implemented', 4))
                    self.assertTrue(report.implemented_scope_complete)
                    self.assertFalse(report.complete)
