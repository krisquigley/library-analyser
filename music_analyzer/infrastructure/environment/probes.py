"""Cheap, read-only discovery. Never import Essentia or TensorFlow."""
import importlib.util
import platform
import shutil
import subprocess
import sys

from music_analyzer.application.dto.doctor import CheckResult


class PythonProbe:
    def check(self) -> CheckResult:
        version = '.'.join(str(part) for part in sys.version_info[:3])
        return CheckResult('python', sys.version_info[:2] >= (3, 11),
                           f'Python {version}; inference compatibility not validated.',
                           'Use Python >=3.11 in an isolated environment; verify Essentia wheel compatibility.')


class PlatformProbe:
    def check(self) -> CheckResult:
        system, machine = platform.system(), platform.machine()
        return CheckResult('platform', bool(system and machine),
                           f'{system or "unknown OS"} / {machine or "unknown CPU"}; hardware support not validated.',
                           'Confirm OS and CPU architecture before selecting an Essentia build.')


class FFmpegProbe:
    def check(self) -> CheckResult:
        remedy = 'Install FFmpeg through your chosen package manager, ensure it is on PATH, and retry doctor.'
        executable = shutil.which('ffmpeg')
        if executable is None:
            return CheckResult('ffmpeg', False, 'FFmpeg not found on PATH.', remedy)
        try:
            result = subprocess.run([executable, '-version'], capture_output=True,
                                    text=True, timeout=5, check=False)
        except (OSError, subprocess.TimeoutExpired, UnicodeError) as error:
            return CheckResult('ffmpeg', False, f'FFmpeg version check failed: {error}', remedy)
        lines = result.stdout.splitlines()
        if result.returncode != 0 or not lines or not lines[0].startswith('ffmpeg version '):
            return CheckResult('ffmpeg', False, 'FFmpeg did not return a successful recognizable version.', remedy)
        return CheckResult('ffmpeg', True, f'{lines[0]}; audio decoding not validated.', '')


class EssentiaProbe:
    def check(self) -> CheckResult:
        remedy = ('Select a compatible Python/Essentia TensorFlow build and install it in the isolated '
                  'environment; discovery alone does not verify TensorFlow operators or models.')
        try:
            available = importlib.util.find_spec('essentia') is not None
        except (ImportError, ValueError, OSError) as error:
            return CheckResult('essentia', False, f'Essentia discovery failed: {error}', remedy)
        detail = ('Essentia module discoverable; import, TensorFlow operators and inference not validated.'
                  if available else 'Essentia module not found in this Python environment.')
        return CheckResult('essentia', available, detail, remedy if not available else '')
