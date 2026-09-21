import unittest

from music_analyzer.application.dto.doctor import CheckResult
from music_analyzer.application.use_cases.run_doctor import RunDoctor


class FakeProbe:
    def __init__(self, result):
        self.result = result
        self.calls = 0

    def check(self):
        self.calls += 1
        return self.result


class RunDoctorTests(unittest.TestCase):
    def test_available_dependencies_do_not_claim_analysis_readiness(self):
        probes = [FakeProbe(CheckResult(name, True, 'found', ''))
                  for name in ('python', 'platform', 'ffmpeg', 'essentia')]
        report = RunDoctor(probes).execute()
        self.assertTrue(report.foundation_ready)
        self.assertFalse(report.analysis_ready)
        self.assertTrue(report.remaining_validation)
        self.assertEqual([p.calls for p in probes], [1, 1, 1, 1])
        self.assertEqual(report.checks, tuple(p.result for p in probes))

    def test_failures_are_actionable_and_do_not_short_circuit(self):
        probes = [FakeProbe(CheckResult('ffmpeg', False, 'not found', 'Install FFmpeg and retry.')),
                  FakeProbe(CheckResult('essentia', False, 'not found', 'Install a compatible Essentia build.'))]
        report = RunDoctor(probes).execute()
        self.assertFalse(report.foundation_ready)
        self.assertEqual([p.calls for p in probes], [1, 1])
        self.assertIn('Install FFmpeg', report.checks[0].remediation)

    def test_empty_probe_configuration_is_rejected(self):
        with self.assertRaises(ValueError):
            RunDoctor([])

    def test_failed_result_requires_remediation(self):
        with self.assertRaises(ValueError):
            CheckResult('ffmpeg', False, 'missing', '')
