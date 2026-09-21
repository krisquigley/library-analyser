import subprocess
import unittest
from unittest.mock import patch

from music_analyzer.infrastructure.environment.probes import (
    PythonProbe, PlatformProbe, FFmpegProbe, EssentiaProbe,
)


class ProbeTests(unittest.TestCase):
    def test_python_minimum(self):
        for version, expected in [((3, 10, 9), False), ((3, 11, 0), True), ((3, 14, 7), True)]:
            with self.subTest(version=version), patch('music_analyzer.infrastructure.environment.probes.sys.version_info', version):
                self.assertEqual(PythonProbe().check().available, expected)

    def test_platform_records_architecture_without_claiming_compatibility(self):
        with patch('platform.system', return_value='Linux'), patch('platform.machine', return_value='aarch64'):
            result = PlatformProbe().check()
        self.assertTrue(result.available)
        self.assertIn('aarch64', result.detail)
        self.assertIn('not validated', result.detail)

    def test_unknown_platform_is_actionable(self):
        with patch('platform.system', return_value=''), patch('platform.machine', return_value=''):
            self.assertFalse(PlatformProbe().check().available)

    @patch('shutil.which', return_value=None)
    def test_ffmpeg_missing(self, which):
        self.assertFalse(FFmpegProbe().check().available)

    @patch('shutil.which', return_value='/tools/ffmpeg')
    @patch('subprocess.run')
    def test_ffmpeg_version_only_bounded_process(self, run, which):
        run.return_value = subprocess.CompletedProcess([], 0, 'ffmpeg version test\nextra', '')
        result = FFmpegProbe().check()
        self.assertTrue(result.available)
        self.assertIn('ffmpeg version test', result.detail)
        run.assert_called_once_with(['/tools/ffmpeg', '-version'], capture_output=True, text=True, timeout=5, check=False)

    @patch('shutil.which', return_value='/tools/ffmpeg')
    @patch('subprocess.run')
    def test_ffmpeg_failures_are_translated(self, run, which):
        for error in (OSError('denied'), subprocess.TimeoutExpired('ffmpeg', 5), UnicodeError('invalid output')):
            with self.subTest(error=error):
                run.side_effect = error
                self.assertFalse(FFmpegProbe().check().available)
        run.side_effect = None
        for code, output in [(1, 'failure'), (0, ''), (0, 'unrelated executable')]:
            run.return_value = subprocess.CompletedProcess([], code, output, '')
            self.assertFalse(FFmpegProbe().check().available)

    @patch('importlib.util.find_spec')
    def test_essentia_discovery_does_not_import_inference(self, find_spec):
        with patch('builtins.__import__', wraps=__import__) as importer:
            find_spec.return_value = object()
            result = EssentiaProbe().check()
            self.assertTrue(result.available)
            self.assertIn('not validated', result.detail)
        find_spec.assert_called_once_with('essentia')
        self.assertFalse(any(c.args[0].split('.')[0] in ('essentia', 'tensorflow') for c in importer.call_args_list))

    @patch('importlib.util.find_spec')
    def test_missing_or_broken_essentia_discovery(self, find_spec):
        find_spec.return_value = None
        self.assertFalse(EssentiaProbe().check().available)
        for error in (ImportError('broken'), ValueError('invalid spec'), OSError('denied')):
            find_spec.side_effect = error
            self.assertFalse(EssentiaProbe().check().available)
