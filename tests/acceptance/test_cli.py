import json
import subprocess
import sys
import unittest


class CliAcceptanceTests(unittest.TestCase):
    def invoke(self, *args):
        return subprocess.run([sys.executable, '-m', 'music_analyzer', *args],
                              capture_output=True, text=True, timeout=15)

    def test_help(self):
        result = self.invoke('--help')
        self.assertEqual(result.returncode, 0)
        self.assertIn('doctor', result.stdout)
        self.assertEqual(result.stderr, '')

    def test_usage_errors(self):
        for args in [(), ('scan',), ('doctor', '--bogus')]:
            result = self.invoke(*args)
            self.assertEqual(result.returncode, 2)
            self.assertEqual(result.stdout, '')
            self.assertIn('usage:', result.stderr)

    def test_real_read_only_doctor(self):
        result = self.invoke('doctor', '--json')
        report = json.loads(result.stdout)
        self.assertEqual(result.returncode, 0 if report['foundation_ready'] else 1)
        self.assertFalse(report['analysis_ready'])
        self.assertEqual([check['name'] for check in report['checks']], ['python', 'platform', 'ffmpeg', 'essentia'])
        self.assertEqual(result.stderr, '')
