import subprocess
import sys
import tempfile
import unittest
import zipfile
from importlib import resources
from pathlib import Path
from unittest import mock


class MusicExplorerPackagingAndCompatibilityTests(unittest.TestCase):
    def test_explorer_assets_are_owned_by_new_installed_package(self):
        package_assets = resources.files('music_explorer.frameworks.explorer.assets')
        app_js = package_assets.joinpath('app/main/main.js').read_text(encoding='utf-8')
        style = package_assets.joinpath('style.css').read_text(encoding='utf-8')
        self.assertIn('renderMoodStrip', app_js)
        self.assertIn('gauge', style.lower())
        self.assertTrue(package_assets.joinpath('vendor/3d-force-graph/3d-force-graph.min.js').is_file())

    def test_standalone_and_analyzer_explorer_assets_remain_mirrored(self):
        root = Path(__file__).resolve().parents[2]
        analyzer_assets = root / 'music_analyzer/frameworks/explorer/assets'
        standalone_assets = root / 'music_explorer/frameworks/explorer/assets'
        def tree(root):
            # #146: the whole tree, including the browser app's modules, file for file.
            return {path.relative_to(root).as_posix(): path.read_bytes() for path in root.rglob('*')
                    if path.is_file() and '__pycache__' not in path.parts}

        standalone, analyzer = tree(standalone_assets), tree(analyzer_assets)
        self.assertEqual(sorted(standalone), sorted(analyzer))
        for name in standalone:
            with self.subTest(asset=name):
                self.assertEqual(standalone[name], analyzer[name])

    def test_legacy_analyzer_cli_documents_compatibility_route(self):
        result = subprocess.run(
            [sys.executable, '-m', 'music_analyzer', 'explorer', '--help'],
            check=True,
            text=True,
            capture_output=True,
        )
        self.assertIn('compatibility', result.stdout.lower())
        self.assertIn('music-explorer', result.stdout)

    def test_legacy_misspelled_console_script_remains_available(self):
        scripts = self._project_scripts()
        self.assertEqual(
            scripts.get('music-exporer'),
            'music_explorer.frameworks.cli.main:main',
        )

    def test_distribution_metadata_includes_new_package_assets_and_compatibility_script(self):
        with tempfile.TemporaryDirectory() as td:
            build = subprocess.run([sys.executable, '-m', 'pip', 'wheel', '.', '-w', td, '--no-deps'], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            build.check_returncode()
            wheel = next(Path(td).glob('music_analyzer-*.whl'))
            with zipfile.ZipFile(wheel) as wheel_archive:
                listing = '\n'.join(wheel_archive.namelist())
                entry_points = wheel_archive.read('music_analyzer-0.1.0.dist-info/entry_points.txt').decode('utf-8')
        self.assertIn('music_explorer/frameworks/explorer/assets/app/main/main.js', listing)
        self.assertIn('music_explorer/frameworks/explorer/assets/style.css', listing)
        for package in ('music_explorer', 'music_analyzer'):
            for module in ('app/domain/playlist-recipe.js', 'app/adapters/gateways/playlist-download-query.js'):
                self.assertIn(f'{package}/frameworks/explorer/assets/{module}', listing)
            self.assertNotIn(f'{package}/frameworks/explorer/assets/app/package.json', listing)
        self.assertIn('music_explorer/frameworks/explorer/assets/vendor/3d-force-graph/3d-force-graph.min.js', listing)
        self.assertIn('music-exporer = music_explorer.frameworks.cli.main:main', entry_points)

    def test_packaging_test_fails_when_pip_is_unavailable_instead_of_silently_skipping(self):
        result_without_pip = subprocess.CompletedProcess(
            args=[sys.executable, '-m', 'pip'],
            returncode=1,
            stdout='/usr/bin/python: No module named pip',
        )
        with mock.patch('tempfile.TemporaryDirectory') as tempdir, \
                mock.patch('subprocess.run', return_value=result_without_pip), \
                mock.patch.object(unittest.TestCase, 'skipTest', side_effect=AssertionError('must not skip')):
            tempdir.return_value.__enter__.return_value = '/tmp/no-pip-build'
            with self.assertRaises(subprocess.CalledProcessError):
                self.test_distribution_metadata_includes_new_package_assets_and_compatibility_script()

    def _project_scripts(self):
        pyproject_path = Path(__file__).resolve().parents[2] / 'pyproject.toml'
        if sys.version_info >= (3, 11):
            import tomllib
            return tomllib.loads(pyproject_path.read_text(encoding='utf-8'))['project']['scripts']
        raise RuntimeError('Python 3.11 or newer is required')


if __name__ == '__main__':
    unittest.main()
