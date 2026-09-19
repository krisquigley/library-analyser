import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class ConfigCliTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.env = dict(os.environ, HOME=str(self.root), XDG_CONFIG_HOME=str(self.root / 'config'),
                        XDG_DATA_HOME=str(self.root / 'data'), PYTHONDONTWRITEBYTECODE='1')

    def invoke(self, *args):
        return subprocess.run([sys.executable, '-m', 'music_analyzer', *args],
                              env=self.env, capture_output=True, text=True, timeout=15)

    def test_defaults_and_no_writes(self):
        result = self.invoke('doctor', '--json')
        settings = json.loads(result.stdout)['settings']
        self.assertFalse(settings['config_loaded'])
        self.assertEqual(settings['database'], str(self.root / 'data/music-analyzer/analysis.sqlite'))
        self.assertEqual(list(self.root.iterdir()), [])

    def test_options_before_or_after_command_and_precedence(self):
        config = self.root / 'settings.toml'
        config.write_text('database = "configured.sqlite"\nmodel_directory = "weights"\n')
        for args in (
            ('--config', str(config), '--database', str(self.root / 'cli.sqlite'), 'doctor', '--json'),
            ('doctor', '--json', '--config', str(config), '--database', str(self.root / 'cli.sqlite')),
        ):
            result = self.invoke(*args)
            report = json.loads(result.stdout)
            self.assertEqual(report['settings']['database'], str(self.root / 'cli.sqlite'))
            self.assertEqual(report['settings']['model_directory'], str(self.root / 'weights'))
            self.assertFalse(report['analysis_ready'])
            self.assertEqual(result.stderr, '')
        result = self.invoke('--config', str(config), 'doctor', '--model-directory', str(self.root / 'cli-models'))
        self.assertIn(str(self.root / 'cli-models'), result.stdout)
        self.assertIn('not validated', result.stdout)
        self.assertEqual(list(self.root.iterdir()), [config])

    def test_invalid_config_returns_actionable_stderr_without_partial_json(self):
        config = self.root / 'invalid.toml'
        for content in (None, 'database = ['):
            if content is not None:
                config.write_text(content)
            result = self.invoke('--config', str(config), 'doctor', '--json')
            self.assertEqual(result.returncode, 2)
            self.assertEqual(result.stdout, '')
            self.assertIn(str(config), result.stderr)
            self.assertIn('--config', result.stderr)
