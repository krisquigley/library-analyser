"""Opt-in artifact and fresh-install acceptance; no models or real music.

RUN_PACKAGING_TESTS=1 python -m unittest tests.packaging.test_distribution -v
Requires setuptools>=77 in the runner and stdlib venv with pip available.
Builds offline from a clean source copy, then builds the wheel from the sdist.
"""
import csv
from email.parser import Parser
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
import venv
import zipfile


ROOT = Path(__file__).resolve().parents[2]


@unittest.skipUnless(os.environ.get('RUN_PACKAGING_TESTS') == '1',
                     'opt-in offline distribution build/install test')
class DistributionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix='music-analyzer-package-')
        cls.addClassCleanup(cls.temp.cleanup)
        cls.root = Path(cls.temp.name)
        source = cls.root / 'source'
        source.mkdir()
        for name in ('pyproject.toml', 'README.md', 'MANIFEST.in'):
            if (ROOT / name).exists():
                shutil.copy2(ROOT / name, source / name)
        for name in ('music_analyzer', 'plans', 'docs'):
            if (ROOT / name).exists():
                shutil.copytree(ROOT / name, source / name,
                                ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
        cls.artifacts = cls.root / 'artifacts'
        cls.artifacts.mkdir()
        cls.run_command([sys.executable, '-c',
            'from setuptools.build_meta import build_sdist; '
            f'build_sdist({str(cls.artifacts)!r})'], source)
        cls.sdist = next(cls.artifacts.glob('*.tar.gz'))
        unpacked = cls.root / 'unpacked'
        with tarfile.open(cls.sdist) as archive:
            # Locally generated trusted archive; do not extract user archives here.
            archive.extractall(unpacked, filter='data')
        cls.run_command([sys.executable, '-c',
            'from setuptools.build_meta import build_wheel; '
            f'build_wheel({str(cls.artifacts)!r})'], next(unpacked.iterdir()))
        cls.wheel = next(cls.artifacts.glob('*.whl'))
        env = cls.root / 'venv'
        venv.EnvBuilder(with_pip=True).create(env)
        cls.python = env / 'bin' / 'python'
        cls.cli = env / 'bin' / 'music-analyzer'
        cls.run_command([str(cls.python), '-m', 'pip', 'install', '--no-index',
                         '--no-deps', str(cls.wheel)], cls.root)
        cls.outside = cls.root / 'outside checkout'
        cls.outside.mkdir()
        cls.environment = {**os.environ, 'HOME': str(cls.outside),
            'XDG_CONFIG_HOME': str(cls.outside / 'config'),
            'XDG_DATA_HOME': str(cls.outside / 'data'),
            'XDG_CACHE_HOME': str(cls.outside / 'cache'),
            'PATH': str(env / 'bin'), 'PYTHONPATH': '', 'PYTHONUTF8': '1'}
        # Optional durable build evidence without keeping a temporary installation.
        if destination := os.environ.get('PACKAGING_ARTIFACT_DIR'):
            Path(destination).mkdir(parents=True, exist_ok=True)
            for artifact in (cls.sdist, cls.wheel):
                shutil.copy2(artifact, destination)

    @staticmethod
    def run_command(command, cwd, env=None, expected=0):
        result = subprocess.run(command, cwd=cwd, env=env, text=True,
                                capture_output=True, timeout=120)
        if result.returncode != expected:
            raise AssertionError(f'{command}: exit {result.returncode}\n'
                                 f'{result.stdout}\n{result.stderr}')
        return result

    def invoke(self, *arguments, expected=0, module=False):
        command = ([str(self.python), '-I', '-m', 'music_analyzer'] if module
                   else [str(self.cli)])
        result = self.run_command(command + list(arguments), self.outside,
                                  self.environment, expected)
        if expected != 2:
            self.assertEqual(result.stderr, '')
        return result

    def test_distribution_preserves_assets_and_metadata(self):
        with zipfile.ZipFile(self.wheel) as wheel:
            names = wheel.namelist()
            for asset in ('manifest.json', 'LICENSE'):
                name = 'music_analyzer/infrastructure/models/data/' + asset
                self.assertEqual(wheel.read(name), (ROOT / name).read_bytes())
            metadata = Parser().parsestr(wheel.read(next(
                name for name in names if name.endswith('.dist-info/METADATA'))).decode())
            self.assertEqual(metadata['Name'], 'music-analyzer')
            self.assertEqual(metadata['Requires-Python'], '>=3.11')
            self.assertIsNone(metadata['Requires-Dist'])
            self.assertFalse(any(name.endswith('.pb') for name in names))

    def test_installed_entrypoints_and_offline_setup_errors(self):
        for module in (False, True):
            self.assertIn('doctor', self.invoke('--help', module=module).stdout)
            report = json.loads(self.invoke('doctor', '--json', expected=1,
                                           module=module).stdout)
            self.assertFalse(report['analysis_ready'])
            self.assertFalse(report['foundation_ready'])
        report = json.loads(self.invoke('models', 'verify', '--json', expected=1).stdout)
        self.assertEqual(len(report['models']), 6)
        self.assertFalse(report['inference_validated'])
        result = self.invoke('doctor', '--bogus', expected=2)
        self.assertEqual(result.stdout, '')
        self.assertIn('usage:', result.stderr)
        self.assertFalse((self.outside / 'data').exists())
        location = self.run_command([str(self.python), '-I', '-c',
            'import music_analyzer; print(music_analyzer.__file__)'], self.outside)
        self.assertIn(str(self.root / 'venv'), location.stdout)

    def test_installed_scan_review_export_without_inference(self):
        selected = self.outside / 'selected 音'
        selected.mkdir()
        original = b'disposable inventory fixture, not valid audio'
        audio = selected / 'été 音.flac'
        audio.write_bytes(original)
        db = self.outside / 'analysis.sqlite'
        def call(*args, **kwargs):
            return self.invoke('--database', str(db), *args, **kwargs)
        scan = json.loads(call('scan', str(selected), '--json').stdout)
        track = scan['files'][0]['track_id']
        self.assertIn(track, call('list', '--needs-review').stdout)
        self.assertIsNone(json.loads(call('show', track, '--json').stdout)['run'])
        annotation = '=formula, "été"\nmanual only'
        call('override', 'set', track, 'genres', annotation)
        for format in ('json', 'csv'):
            output = self.outside / ('review.' + format)
            call('export', '--format', format, '--output', str(output))
            if format == 'json':
                record = json.loads(output.read_text())[0]
            else:
                with output.open(newline='') as stream:
                    row = next(csv.DictReader(stream))
                self.assertEqual(row['override_genres'], "'" + annotation)
                record = json.loads(row['record'])
            self.assertEqual(record['effective']['genres'], annotation)
            before = output.read_bytes()
            # Export errors use stderr, unlike setup/model JSON reports.
            result = self.run_command([str(self.cli), '--database', str(db),
                'export', '--format', format, '--output', str(output)],
                self.outside, self.environment, expected=1)
            self.assertEqual(result.stdout, '')
            self.assertTrue(result.stderr)
            self.assertEqual(output.read_bytes(), before)
        call('override', 'clear', track, 'genres')
        self.assertEqual(json.loads(call('show', track, '--json').stdout)['overrides'], {})
        self.assertEqual(audio.read_bytes(), original)
