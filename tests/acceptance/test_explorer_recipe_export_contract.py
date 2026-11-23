"""Issue #139: a recipe the Explorer exports is one `music-analyzer playlist-recipe save` accepts.

The Explorer never saves recipes; it exports a file for the analyzer to store. The browser builds that file
(app/domain/playlist-recipe-document.js), so this test runs it in Node on synthetic drafts and hands each
result to the analyzer's own recipe parser.
"""
import json
import shutil
import subprocess
import unittest
from pathlib import Path

from music_analyzer.domain.playlist_recipe import parse_playlist_recipe

ROOT = Path(__file__).resolve().parents[2]
START = 'sha256:' + 'd' * 64
DRAFTS = [
    {},
    {'durationMinutes': '75', 'harmonicMixing': False, 'moodHold': 'calm'},
    {'energyArcs': [{'shape': 'peak', 'length': '', 'low': '0.1', 'high': '0.9'}]},
    {'energyArcs': [{'shape': 'rise', 'length': '8', 'low': '', 'high': '0.8'},
                    {'shape': 'steady', 'length': '4', 'low': '', 'high': ''},
                    {'shape': 'dip', 'length': '8', 'low': '', 'high': ''}]},
    {'arcLengthUnit': 'minutes', 'energyArcs': [{'shape': 'fall', 'length': '30.5', 'low': '', 'high': ''},
                                                {'shape': 'rise', 'length': '20', 'low': '', 'high': ''}]},
    {'minimumKeyStrength': '0'},
]
SCRIPT = r'''
const assets = process.argv[1];
const {playlistRecipeDocument} = await import(assets + '/domain/playlist-recipe-document.js');
const {EMPTY_PLAYLIST_DRAFT} = await import(assets + '/domain/playlist-draft.js');
const [start, drafts] = [process.argv[2], JSON.parse(process.argv[3])];
console.log(JSON.stringify(drafts.map(changes =>
  playlistRecipeDocument({...EMPTY_PLAYLIST_DRAFT, bpmMin: '98', bpmMax: '126.5', ...changes}, start))));
'''


@unittest.skipUnless(shutil.which('node'), 'Node is required to run the browser app')
class ExportedRecipeContractTests(unittest.TestCase):
    def test_every_exported_recipe_is_accepted_by_the_analyzer(self):
        for package in ('music_explorer', 'music_analyzer'):
            app = (ROOT / package / 'frameworks/explorer/assets/app').as_uri()
            with self.subTest(package=package):
                result = subprocess.run(['node', '--input-type=module', '-e', SCRIPT, app, START, json.dumps(DRAFTS)],
                                        capture_output=True, text=True, timeout=30, cwd=ROOT)
                self.assertEqual(0, result.returncode, result.stderr)
                documents = json.loads(result.stdout)
                self.assertEqual(len(DRAFTS), len(documents))
                for document in documents:
                    with self.subTest(document=document):
                        self.assertEqual(START, parse_playlist_recipe(document).start_track_id)


if __name__ == '__main__':
    unittest.main()
