"""Public browser instructions preserve explicit consent and honest scope."""
from pathlib import Path
import unittest

class BrowserDiagnosticDocumentation(unittest.TestCase):
    def test_public_browser_scope_and_safety_are_explicit(self):
        path = Path(__file__).resolve().parents[3] / 'docs/explorer-browser-diagnostic.md'
        self.assertTrue(path.exists(), 'Browser diagnostic documentation is required')
        text = path.read_text()
        for phrase in ('--real-browser', '--graph-profile small', '--allow-large',
                       'stress-41mib', 'memory.max', 'memory.oom.group',
                       'XDG_CONFIG_HOME', 'XDG_CACHE_HOME', 'SIGKILL', 'scratch',
                       'process-cold', 'nearest-rank', '41 * 2**20',
                       'SQLite', 'not a latency budget', 'full CI'):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, text)
