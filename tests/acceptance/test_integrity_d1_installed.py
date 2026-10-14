"""Offline installed-wheel delivery controls; not missing-behavior RED evidence."""
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import tempfile
import unittest
import venv

from tests.integration.infrastructure.integrity_d1_public_fixture import create_public_core_database
from tests.integration.infrastructure.integrity_d2_public_fixture import create_public_graph_database


class IntegrityD1InstalledControls(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if os.environ.get('RUN_PACKAGING_TESTS') == '0':
            raise unittest.SkipTest('RUN_PACKAGING_TESTS=0 disables installed-wheel packaging controls')
        cls.scratch = tempfile.TemporaryDirectory(prefix='integrity-d1-installed-')
        cls.root = Path(cls.scratch.name)
        cls.outside = cls.root / 'outside'
        cls.outside.mkdir()
        cls.environment = dict(os.environ, PIP_NO_INDEX='1', PIP_NO_CACHE_DIR='1')
        cls.environment.pop('PYTHONPATH', None)
        cls.environment.pop('PYTHONHOME', None)
        cls.environment['XDG_CONFIG_HOME'] = str(cls.root / 'PRIVATE-config')
        cls.venv = cls.root / 'venv'
        venv.EnvBuilder(with_pip=True).create(cls.venv)
        cls.python = cls.venv / 'bin/python'
        cls.script = cls.venv / 'bin/music-analyzer'
        cls.run_child([str(cls.python), '-m', 'pip', 'install', '--no-deps', '--no-index',
                       '--find-links', '/usr/share/python-wheels', 'setuptools>=77'], cls.outside, expected=0)
        repository = Path(__file__).resolve().parents[2]
        wheels = cls.root / 'wheels'
        cls.run_child([str(cls.python), '-m', 'pip', 'wheel', str(repository), '--no-build-isolation',
                       '--no-deps', '--no-index', '--find-links', '/usr/share/python-wheels',
                       '--wheel-dir', str(wheels)], cls.outside, expected=0)
        wheel, = wheels.glob('music_analyzer-*.whl')
        print('offline installed wheel SHA256', hashlib.sha256(wheel.read_bytes()).hexdigest())
        cls.run_child([str(cls.python), '-m', 'pip', 'install', '--no-deps', '--no-index',
                       '--find-links', '/usr/share/python-wheels', str(wheel)], cls.outside, expected=0)
        origin = cls.run_child([str(cls.python), '-c', 'import music_analyzer; print(music_analyzer.__file__)'], cls.outside, expected=0)
        if str(cls.venv) not in origin.stdout:
            raise AssertionError('Installed origin must be isolated venv, not checkout')
        print('installed origin verified outside checkout:', origin.stdout.strip())

    @classmethod
    def tearDownClass(cls):
        cls.scratch.cleanup()

    @classmethod
    def run_child(cls, args, cwd=None, expected=None):
        result = subprocess.run(args, cwd=cwd or cls.outside, env=cls.environment,
                                capture_output=True, text=True, timeout=120)
        print('owned offline command', repr(args), 'cwd', str(cwd or cls.outside), 'exit', result.returncode)
        if expected is not None and result.returncode != expected:
            raise AssertionError(f'Owned child expected exit{expected}, actual{result.returncode}: {result.stderr}')
        return result

    def test_true6_to10_script_and_module_are_limited_without_target_mutation(self):
        for version in range(6, 11):
            path = self.root / f'public-v{version}.sqlite'
            create_public_core_database(path, version)
            before = path.read_bytes()
            for command in ([str(self.script)], [str(self.python), '-m', 'music_analyzer']):
                with self.subTest(version=version, entry=command[-1]):
                    result = self.run_child(command + ['integrity', '--database', str(path), '--json'], expected=4)
                    report = json.loads(result.stdout)
                    self.assertEqual(report['status'], 'incomplete')
                    self.assertFalse(report['complete'])
                    self.assertTrue(report['implemented_scope_complete'])
                    self.assertEqual(report['stop_reason'], 'scope_not_implemented')
                    self.assertEqual(report['schema_version'], version)
                    checks = {c['check_id']: c for c in report['checks']}
                    self.assertEqual(len(checks), 12)
                    for name in ('schema', 'core_rows', 'resource_access'):
                        self.assertEqual(checks[name]['state'], 'completed')
                    self.assertEqual(checks['core_rows']['count'], 4)
                    self.assertEqual(checks['current_graph']['state'], 'not_applicable' if version == 6 else 'completed')
                    self.assertEqual(checks['current_evidence']['state'], 'not_applicable' if version < 9 else 'not_implemented')
                    self.assertEqual(result.stderr, '')
                    self.assertNotIn(str(path), result.stdout)
                    self.assertEqual(path.read_bytes(), before)

    def test_installed_graph_healthy_and_corrupt_are_selected_complete_but_incomplete(self):
        for version in range(7, 11):
            path = self.root / f'public-graph-v{version}.sqlite'
            create_public_graph_database(path, version)
            for corrupt in (False, True):
                if corrupt:
                    with closing(sqlite3.connect(path)) as db:
                        db.execute('UPDATE graph_edges SET score=0.6,distance=0.4')
                        db.commit()
                before = path.read_bytes()
                for command in ([str(self.script)], [str(self.python), '-m', 'music_analyzer']):
                    with self.subTest(version=version, corrupt=corrupt, entry=command[-1]):
                        result = self.run_child(command + ['integrity', '--database', str(path), '--json'], expected=4)
                        report = json.loads(result.stdout)
                        self.assertEqual(report['coverage_revision'], 'D2a')
                        self.assertEqual(report['status'], 'incomplete')
                        self.assertFalse(report['complete'])
                        self.assertTrue(report['implemented_scope_complete'])
                        checks = {c['check_id']: c for c in report['checks']}
                        for owner, count in zip(('current_graph', 'historical_graph'),
                                                (2, 4) if version == 7 else (3, 8)):
                            self.assertEqual((checks[owner]['state'], checks[owner]['count'],
                                              checks[owner]['count_precision']), ('completed', count, 'exact'))
                        graph_findings = [f for f in report['findings'] if f['check_id'].endswith('_graph')]
                        self.assertEqual([(f['check_id'], f['code'], f['count'], f['count_precision'])
                                          for f in graph_findings],
                                         [('current_graph', 'graph_mirror_invalid', 1, 'exact')] if corrupt else [])
                        self.assertEqual(result.stderr, '')
                        self.assertEqual(path.read_bytes(), before)

    def test_corruption_schema_blocked_unsupported_and_usage_exits_are_honest(self):
        path = self.root / 'public-errors.sqlite'
        create_public_core_database(path, 6)
        with closing(sqlite3.connect(path)) as db:
            db.execute('UPDATE tracks SET size=-1 WHERE rowid=(SELECT MAX(rowid) FROM tracks)')
            db.commit()
        result = self.run_child([str(self.script), 'integrity', '--database', str(path), '--json'], expected=4)
        report = json.loads(result.stdout)
        self.assertIn('track_size_invalid', [f['code'] for f in report['findings']])
        self.assertTrue(report['implemented_scope_complete'])
        with closing(sqlite3.connect(path)) as db:
            db.execute('CREATE TABLE extra_private(payload TEXT)')
            db.commit()
        report = json.loads(self.run_child([str(self.script), 'integrity', '--database', str(path), '--json'], expected=4).stdout)
        self.assertEqual(report['stop_reason'], 'schema_blocked')
        self.assertFalse(report['implemented_scope_complete'])
        self.assertEqual(next(c for c in report['checks'] if c['check_id'] == 'core_rows')['state'], 'blocked')
        with closing(sqlite3.connect(path)) as db:
            db.execute('PRAGMA application_id=123')
        report = json.loads(self.run_child([str(self.script), 'integrity', '--database', str(path), '--json'], expected=3).stdout)
        self.assertIsNone(report['schema_version'])
        invalid = self.run_child([str(self.script), 'integrity', '--database', 'PRIVATE-target', '--PRIVATE-option'], expected=2)
        self.assertNotIn('PRIVATE', invalid.stdout + invalid.stderr)
        missing = self.run_child([str(self.script), 'integrity'], expected=2)
        self.assertEqual(missing.stdout, '')

    def test_existing_doctor_scripts_version_and_packaged_assets_remain_available(self):
        result = self.run_child([str(self.script), 'doctor', '--json'])
        self.assertIn(result.returncode, (0, 1))
        self.assertIsInstance(json.loads(result.stdout), dict)
        for script in ('music-explorer', 'music-exporer'):
            self.run_child([str(self.venv / 'bin' / script), '--help'], expected=0)
        result = self.run_child([str(self.python), '-c',
            "import importlib.metadata as m; from importlib.resources import files; "
            "assert m.version('music-analyzer')=='0.1.0'; "
            "assert files('music_explorer.frameworks.explorer').joinpath('assets/index.html').is_file(); "
            "assert files('music_analyzer.infrastructure.models').joinpath('data/manifest.json').is_file(); "
            "print('package compatibility verified')"], expected=0)
        self.assertIn('verified', result.stdout)
