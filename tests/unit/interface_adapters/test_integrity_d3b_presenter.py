"""Final D3 text and JSON agreement independent of scanner implementation."""
from dataclasses import replace
import json
import unittest

from music_analyzer.application.dto.integrity import IntegrityReport
from music_analyzer.interface_adapters.presenters.integrity import present_integrity
from tests.unit.application.test_integrity_d3b_completion import CountedAssertions, completed_scan, corruption


def final_report(corrupt=False):
    scan = completed_scan()
    return IntegrityReport(10, 'corrupt' if corrupt else 'clean', True, 'completed',
                           1 if corrupt else 0, scan.checks,
                           (corruption(),) if corrupt else (), False,
                           coverage_revision='D3', complete=True)


class D3bPresenterTests(CountedAssertions):
    def test_complete_text_and_json_agree_for_clean_and_corrupt(self):
        for corrupt in (False, True):
            report = final_report(corrupt)
            text = present_integrity(report)
            wire = json.loads(present_integrity(report, as_json=True))
            with self.subTest(corrupt=corrupt):
                self.assertIn(' complete=true ', text)
                self.assertNotIn('not P7 complete', text)
                self.assertNotIn('LIMITED', text)
                self.assertIn('status=' + wire['status'], text)
                self.assertIn('exit=' + str(wire['exit_code']), text)
                self.assertTrue(wire['complete'])
                self.assertEqual(wire['coverage_revision'], 'D3')
                self.assertEqual([c['check_id'] for c in wire['checks']], [c.check_id for c in report.checks])

    def test_json_static_finite_fields_and_counts_are_controls(self):
        report = final_report(True)
        raw = present_integrity(report, as_json=True)
        wire = json.loads(raw)
        self.assertEqual(set(wire), {'report_version', 'coverage_revision', 'required_scope_revision',
                                    'supported_schema_versions', 'schema_version', 'status', 'complete',
                                    'implemented_scope_complete', 'stop_reason', 'exit_code', 'checks',
                                    'findings', 'findings_truncated'})
        self.assertEqual(wire['findings'], [{'check_id': 'sqlite_physical',
            'code': 'sqlite_integrity_invalid', 'severity': 'corruption', 'count': 1,
            'count_unit': 'occurrences', 'count_precision': 'exact'}])
        self.assertEqual((wire['report_version'], wire['required_scope_revision']), (1, 'P7-1'))
        for forbidden in ('PRIVATE', 'rowid', 'SELECT ', 'Traceback', 'payload', '/public/'):
            self.assertNotIn(forbidden, raw)

    def test_incomplete_text_and_json_remain_false_controls(self):
        report = replace(final_report(), status='incomplete', complete=False,
                         implemented_scope_complete=False, stop_reason='cleanup_error', exit_code=4)
        wire = json.loads(present_integrity(report, as_json=True))
        text = present_integrity(report)
        self.assertFalse(wire['complete'])
        self.assertIn(' complete=false ', text)
        self.assertIn('status=incomplete', text)
        self.assertIn('exit=4', text)
