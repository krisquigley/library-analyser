import subprocess
import sys
import tempfile
import unittest
from importlib import resources
from pathlib import Path


class MusicExplorerPackagingAndCompatibilityTests(unittest.TestCase):
    def test_explorer_assets_are_owned_by_new_installed_package(self):
        package_assets = resources.files('music_explorer.frameworks.explorer.assets')
        app_js = package_assets.joinpath('app.js').read_text(encoding='utf-8')
        style = package_assets.joinpath('style.css').read_text(encoding='utf-8')
        self.assertIn('buildMoodStrip', app_js)
        self.assertIn('gauge', style.lower())
        self.assertTrue(package_assets.joinpath('vendor/3d-force-graph/3d-force-graph.min.js').is_file())

    def test_standalone_and_analyzer_explorer_assets_remain_mirrored(self):
        root = Path(__file__).resolve().parents[2]
        analyzer_assets = root / 'music_analyzer/frameworks/explorer/assets'
        standalone_assets = root / 'music_explorer/frameworks/explorer/assets'
        for name in ['app.js', 'style.css']:
            with self.subTest(asset=name):
                self.assertEqual(
                    analyzer_assets.joinpath(name).read_text(encoding='utf-8'),
                    standalone_assets.joinpath(name).read_text(encoding='utf-8'),
                )

    def test_legacy_analyzer_cli_documents_compatibility_route(self):
        result = subprocess.run(
            [sys.executable, '-m', 'music_analyzer', 'explorer', '--help'],
            check=True,
            text=True,
            capture_output=True,
        )
        self.assertIn('compatibility', result.stdout.lower())
        self.assertIn('music-explorer', result.stdout)

    def test_distribution_metadata_includes_new_package_and_assets(self):
        with tempfile.TemporaryDirectory() as td:
            build = subprocess.run([sys.executable, '-m', 'pip', 'wheel', '.', '-w', td, '--no-deps'], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            if build.returncode != 0 and 'No module named pip' in build.stdout:
                self.skipTest('pip is not installed in this runtime')
            build.check_returncode()
            wheel = next(Path(td).glob('music_analyzer-*.whl'))
            listing = subprocess.check_output([sys.executable, '-m', 'zipfile', '-l', str(wheel)], text=True)
        self.assertIn('music_explorer/frameworks/explorer/assets/app.js', listing)
        self.assertIn('music_explorer/frameworks/explorer/assets/style.css', listing)
        self.assertIn('music_explorer/frameworks/explorer/assets/vendor/3d-force-graph/3d-force-graph.min.js', listing)


if __name__ == '__main__':
    unittest.main()
