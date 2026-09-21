import contextlib
import io
import json
import unittest
from unittest.mock import patch

from music_analyzer.application.dto.doctor import CheckResult
from music_analyzer.application.use_cases.run_doctor import RunDoctor
from music_analyzer.frameworks.cli.main import main
from tests.unit.application.test_run_doctor import FakeProbe


class DoctorCliTests(unittest.TestCase):
    def invoke(self, args, available=True):
        use_case = RunDoctor([FakeProbe(CheckResult('example', available, 'detail with "quotes"',
                                                     '' if available else 'Fix dependency.'))])
        stdout, stderr = io.StringIO(), io.StringIO()
        with patch('music_analyzer.frameworks.cli.main.build_doctor', return_value=use_case), contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = main(args)
        return code, stdout.getvalue(), stderr.getvalue()

    def test_json_success_and_setup_failure(self):
        for available in (True, False):
            with self.subTest(available=available):
                code, stdout, stderr = self.invoke(['doctor', '--json'], available)
                payload = json.loads(stdout)
                self.assertEqual(code, 0 if available else 1)
                self.assertEqual(payload['foundation_ready'], available)
                self.assertFalse(payload['analysis_ready'])
                self.assertTrue(payload['remaining_validation'])
                self.assertEqual(payload['checks'][0]['name'], 'example')
                self.assertEqual(stderr, '')

    def test_human_report_and_remediation_on_stdout(self):
        code, stdout, stderr = self.invoke(['doctor'], False)
        self.assertEqual(code, 1)
        self.assertIn('FAIL example', stdout)
        self.assertIn('Fix dependency.', stdout)
        self.assertIn('Analysis ready: no', stdout)
        self.assertEqual(stderr, '')

    def test_unexpected_error_is_diagnostic_not_json(self):
        stdout, stderr = io.StringIO(), io.StringIO()
        with patch('music_analyzer.frameworks.cli.main.build_doctor', side_effect=RuntimeError('probe broke')), contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = main(['doctor', '--json'])
        self.assertEqual(code, 1)
        self.assertEqual(stdout.getvalue(), '')
        self.assertIn('probe broke', stderr.getvalue())
