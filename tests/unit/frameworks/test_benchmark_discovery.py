"""CI discovery runs every test module and never shadows the repository's own packages (#184)."""
from pathlib import Path
import subprocess
import sys
import unittest


class BenchmarkDiscoveryTests(unittest.TestCase):
    def test_unit_discovery_keeps_the_production_benchmark_importable(self):
        root = Path(__file__).resolve().parents[3]
        # Load, but do not run, each suite in a fresh interpreter: discovery's
        # sys.path and module-cache changes are the behavior under test.
        script = """
import importlib
from pathlib import Path
import sys
import unittest

suite = unittest.TestLoader().discover(sys.argv[1], pattern=sys.argv[2], top_level_dir='.')
benchmark = importlib.import_module('tools.graph_read_benchmark')
expected = Path('tools/graph_read_benchmark.py').resolve()
assert Path(benchmark.__file__).resolve() == expected, benchmark.__file__
assert suite.countTestCases() >= 12, suite.countTestCases()
explorer = importlib.import_module('music_explorer.interface_adapters.playlist_recipe_query')
assert Path(explorer.__file__).resolve() == Path('music_explorer/interface_adapters/playlist_recipe_query.py').resolve()
"""
        for start, pattern in (
            ('tests/unit', 'test_graph_read_benchmark*.py'),
            ('tests/unit', 'test*.py'),
        ):
            with self.subTest(start=start, pattern=pattern):
                result = subprocess.run(
                    [sys.executable, '-c', script, start, pattern],
                    cwd=root, capture_output=True, text=True, timeout=30,
                    check=False,
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


    def test_every_directory_of_test_modules_is_a_package_discovery_descends_into(self):
        root = Path(__file__).resolve().parents[3]
        hidden = sorted(str(directory.relative_to(root)) for directory in (root / 'tests').rglob('*')
                        if directory.is_dir() and any(directory.glob('test_*.py'))
                        and not (directory / '__init__.py').exists())
        self.assertEqual([], hidden, 'unittest discovery skips a directory without __init__.py')


if __name__ == '__main__':
    unittest.main()
