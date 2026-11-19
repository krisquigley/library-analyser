"""Run the Explorer browser app's unit tests (`node --test`) from unittest (#146).

Domain and application modules are tested in Node, without a DOM or a network.
"""
import shutil
import subprocess
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[2]


@unittest.skipUnless(shutil.which('node'), 'Node is required for the browser app unit tests')
class ExplorerAppUnitTests(unittest.TestCase):
    def test_the_browser_app_unit_tests_pass(self):
        test_files = sorted(str(path.relative_to(REPO_ROOT)) for path in HERE.rglob('*.test.js'))
        self.assertTrue(test_files, 'no browser app unit tests were found')
        result = subprocess.run(['node', '--test', *test_files], cwd=REPO_ROOT,
                                capture_output=True, text=True, timeout=120)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
