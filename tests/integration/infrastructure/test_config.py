from pathlib import Path
import tempfile
import unittest

from music_analyzer.infrastructure.config import ConfigurationError, load_settings


class ConfigTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.env = {'HOME': str(self.root)}

    def load(self, **kwargs):
        return load_settings(environment=self.env, cwd=self.root, **kwargs)

    def test_defaults_and_relative_xdg_are_read_only(self):
        for value in ('', 'relative'):
            self.env.update(XDG_CONFIG_HOME=value, XDG_DATA_HOME=value)
            settings = self.load()
            self.assertEqual(settings.database, str(self.root / '.local/share/music-analyzer/analysis.sqlite'))
            self.assertEqual(settings.model_directory, str(self.root / '.local/share/music-analyzer/models'))
            self.assertEqual(settings.config_file, str(self.root / '.config/music-analyzer/config.toml'))
            self.assertFalse(settings.config_loaded)
            self.assertEqual(list(self.root.iterdir()), [])

    def test_absolute_xdg_and_implicit_config(self):
        self.env.update(XDG_CONFIG_HOME=str(self.root / 'config'), XDG_DATA_HOME=str(self.root / 'data'))
        config = self.root / 'config/music-analyzer/config.toml'
        config.parent.mkdir(parents=True)
        config.write_text('database = "db.sqlite"\nmodel_directory = "weights"\n')
        before = sorted(self.root.rglob('*'))
        settings = self.load()
        self.assertTrue(settings.config_loaded)
        self.assertEqual(settings.database, str(config.parent / 'db.sqlite'))
        self.assertEqual(settings.model_directory, str(config.parent / 'weights'))
        self.assertEqual(sorted(self.root.rglob('*')), before)
        config.write_text('')
        self.assertEqual(self.load().database, str(self.root / 'data/music-analyzer/analysis.sqlite'))

    def test_explicit_config_and_cli_precedence(self):
        config = self.root / 'custom.toml'
        config.write_text('database = "configured.sqlite"\nmodel_directory = "configured-models"\n')
        settings = self.load(config='custom.toml', database='cli.sqlite', model_directory='/absolute/models')
        self.assertEqual(settings.database, str(self.root / 'cli.sqlite'))
        self.assertEqual(settings.model_directory, '/absolute/models')
        self.assertEqual(settings.config_file, str(config))

    def test_missing_explicit_and_invalid_config_are_actionable(self):
        with self.assertRaisesRegex(ConfigurationError, 'missing.toml.*--config'):
            self.load(config='missing.toml')
        config = self.root / 'bad.toml'
        for text in ('database = [', 'database = 3', 'database = " "', 'unknown = "x"', '[paths]\ndatabase = "x"', 'database = "\\u0000"'):
            config.write_text(text)
            with self.subTest(text=text), self.assertRaisesRegex(ConfigurationError, 'bad.toml'):
                self.load(config=str(config), database='override.sqlite')

    def test_invalid_path_types_and_cli_values(self):
        file = self.root / 'file'
        file.write_text('')
        for kwargs in ({'database': str(self.root)}, {'model_directory': str(file)}, {'database': ''}, {'model_directory': '\x00'},
                       {'database': str(file / 'db.sqlite')}, {'model_directory': str(file / 'models')}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ConfigurationError):
                self.load(**kwargs)

    def test_explicit_config_directory_is_not_silently_ignored(self):
        with self.assertRaisesRegex(ConfigurationError, '--config'):
            self.load(config=str(self.root))
