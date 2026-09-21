import unittest

from music_analyzer.application.dto.settings import Settings
from music_analyzer.application.dto.doctor import CheckResult
from music_analyzer.application.use_cases.run_doctor import RunDoctor
from tests.unit.application.test_run_doctor import FakeProbe


class SettingsDoctorTests(unittest.TestCase):
    def test_doctor_reports_settings_without_promising_model_readiness(self):
        settings = Settings('/config.toml', False, '/analysis.sqlite', '/models')
        report = RunDoctor([FakeProbe(CheckResult('example', True, 'available', ''))], settings=settings).execute()
        self.assertEqual(report.settings, settings)
        self.assertTrue(report.foundation_ready)
        self.assertFalse(report.analysis_ready)
        self.assertFalse(any('not implemented' in item and 'Configuration' in item for item in report.remaining_validation))
        self.assertTrue(any('model' in item.lower() for item in report.remaining_validation))
