"""Issue #139: save, list, show and delete playlist recipes from the analyzer's command line."""
from contextlib import redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest

from music_analyzer.frameworks.cli.main import main
from tests.integration.infrastructure.integrity_d1_public_fixture import PUBLIC_TRACK_IDS, create_public_core_database

START = PUBLIC_TRACK_IDS[0]


class PlaylistRecipeCLITests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.database = self.root / 'analysis.sqlite'
        create_public_core_database(self.database, 11)

    def call(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = main(['--database', str(self.database), 'playlist-recipe', *args])
        return code, out.getvalue(), err.getvalue()

    def recipe_file(self, document, name='recipe.json'):
        path = self.root / name
        path.write_text(json.dumps(document) if not isinstance(document, str) else document, encoding='utf-8')
        return str(path)

    def recipe(self, **fields):
        return {'format': 'playlist-recipe', 'version': 1, 'start_track_id': START, 'bpm': {'min': 100, 'max': 130},
                'energy_plan': [{'shape': 'rise', 'tracks': 6}, {'shape': 'fall', 'tracks': 6}], **fields}

    def test_save_list_show_and_delete(self):
        self.assertEqual((0, 'Saved playlist recipe "Friday warm-up"\n', ''),
                         self.call('save', '--name', ' Friday warm-up ', '--file', self.recipe_file(self.recipe())))

        code, out, err = self.call('list')
        self.assertEqual((0, ''), (code, err))
        lines = out.splitlines()
        self.assertEqual('NAME\tSTART_TRACK\tUPDATED\tPROBLEM', lines[0])
        self.assertEqual(['Friday warm-up', START], lines[1].split('\t')[:2])
        self.assertEqual('', lines[1].split('\t')[3])

        code, out, err = self.call('show', 'Friday warm-up')
        self.assertEqual((0, ''), (code, err))
        shown = json.loads(out)
        self.assertEqual(['rise', 'fall'], [arc['shape'] for arc in shown['energy_plan']])
        self.assertEqual(0, self.call('save', '--name', 'Copy', '--file', self.recipe_file(shown, 'shown.json'))[0],
                         'what show prints can be saved back')

        self.assertEqual((0, 'Deleted playlist recipe "Copy"\n', ''), self.call('delete', 'Copy'))
        self.assertEqual(['Friday warm-up'], [line.split('\t')[0] for line in self.call('list')[1].splitlines()[1:]])

    def test_list_as_json(self):
        self.call('save', '--name', 'A', '--file', self.recipe_file(self.recipe()))

        code, out, _err = self.call('list', '--json')

        self.assertEqual(0, code)
        self.assertEqual([{'name': 'A', 'start_track_id': START, 'problem': None}],
                         [{key: row[key] for key in ('name', 'start_track_id', 'problem')} for row in json.loads(out)])

    def test_replacing_needs_asking_for(self):
        self.call('save', '--name', 'A', '--file', self.recipe_file(self.recipe()))

        code, _out, err = self.call('save', '--name', 'A', '--file', self.recipe_file(self.recipe(mood_hold='calm')))
        self.assertEqual(1, code)
        self.assertIn('A recipe named "A" already exists', err)

        self.assertEqual((0, 'Replaced playlist recipe "A"\n', ''),
                         self.call('save', '--name', 'A', '--replace', '--file', self.recipe_file(self.recipe(mood_hold='calm'))))
        self.assertEqual('calm', json.loads(self.call('show', 'A')[1])['mood_hold'])

    def test_errors_name_what_to_fix_and_store_nothing(self):
        for args, message in (
                (('--name', 'A', '--file', 'MISSING'), 'cannot read the recipe file'),
                (('--name', 'A', '--file', '{not json'), 'is not valid JSON'),
                (('--name', 'A', '--file', {**self.recipe(), 'tempo': 1}), 'Unknown recipe field: tempo'),
                (('--name', 'A', '--file', self.recipe(start_track_id='sha256:gone')),
                 'start track sha256:gone is not in the analysis database'),
                (('--name', '   ', '--file', self.recipe()), 'A recipe name is 1 to 100 printable characters')):
            with self.subTest(message=message):
                args = list(args)
                if args[3] == 'MISSING':
                    args[3] = str(self.root / 'missing.json')
                elif args[3] != 'MISSING':
                    args[3] = self.recipe_file(args[3])
                code, out, err = self.call('save', *args)
                self.assertEqual((1, ''), (code, out))
                self.assertIn(message, err)
        self.assertEqual(['NAME\tSTART_TRACK\tUPDATED\tPROBLEM'], self.call('list')[1].splitlines())

    def test_show_or_delete_an_unknown_recipe(self):
        for command in ('show', 'delete'):
            with self.subTest(command=command):
                code, out, err = self.call(command, 'Nope')
                self.assertEqual((1, ''), (code, out))
                self.assertIn('No recipe named "Nope"', err)


if __name__ == '__main__':
    unittest.main()
