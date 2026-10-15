"""Fresh presenter packet over sanitized application output, no SQLite."""
import json
import unittest
from dataclasses import asdict, replace

from music_analyzer.application.dto.integrity import IntegrityFinding
from music_analyzer.application.use_cases.check_integrity import CheckIntegrity
from music_analyzer.interface_adapters.presenters.integrity import present_integrity
from tests.unit.application.test_integrity_d1_report import FakeScanner, healthy_scan


class IntegrityD1Presenter(unittest.TestCase):
    def test_json_exact_frozen_envelope_and_order(self):
        report = CheckIntegrity(FakeScanner(healthy_scan(6))).execute('PRIVATE TARGET.sqlite')
        expected = {
            'report_version': 1, 'coverage_revision': 'D3a', 'required_scope_revision': 'P7-1',
            'supported_schema_versions': [6, 7, 8, 9, 10], 'schema_version': 6,
            'status': 'incomplete', 'complete': False, 'implemented_scope_complete': True,
            'stop_reason': 'scope_not_implemented', 'exit_code': 4,
            'checks': [asdict(c) for c in report.checks], 'findings': [], 'findings_truncated': False,
        }
        output = present_integrity(report, as_json=True)
        actual = json.loads(output)
        for key, value in expected.items():
            with self.subTest(field=key):
                self.assertEqual(actual.get(key), value, 'frozen report field must be serialized')
        self.assertEqual(list(actual), list(expected), 'wire order must be deterministic')

    def test_text_carries_limited_revisions_checks_units_and_findings(self):
        scan = replace(healthy_scan(10), findings=(IntegrityFinding(
            'core_rows', 'track_size_invalid', 'corruption', 1, count_precision='exact'),))
        report = CheckIntegrity(FakeScanner(scan)).execute('PRIVATE TARGET.sqlite')
        output = present_integrity(report)
        for label in ('LIMITED', 'D3a', 'P7-1', 'incomplete', 'scope_not_implemented',
                      'exit=4', 'track_size_invalid', 'occurrences', 'exact'):
            with self.subTest(label=label):
                self.assertIn(label, output)
        for check in report.checks:
            with self.subTest(check=check.check_id):
                self.assertIn(check.check_id, output)
                self.assertIn(check.count_unit, output)
        self.assertNotIn('PRIVATE', output)

    def test_malformed_boundary_output_cannot_leak_and_is_repeatable(self):
        scan = replace(healthy_scan(6), stop_reason='PRIVATE PATH SQL PAYLOAD')
        report = CheckIntegrity(FakeScanner(scan)).execute('PRIVATE TARGET.sqlite')
        for as_json in (False, True):
            output = present_integrity(report, as_json)
            with self.subTest(format=as_json):
                self.assertIn('read_error', output, 'sanitized fallback must be visible')
                self.assertNotIn('PRIVATE', output)
                self.assertEqual(output, present_integrity(report, as_json))
