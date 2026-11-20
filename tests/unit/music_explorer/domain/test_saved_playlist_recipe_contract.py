"""Issue #139: the Explorer reads saved recipes with its own parser, which must agree with the analyzer's.

The packages never import each other's inner layers; this contract test is what keeps the two parsers in step.
"""
import unittest

from music_analyzer.domain import playlist_recipe as analyzer
from music_explorer.domain import saved_playlist_recipe as explorer

START = 'sha256:' + 'c' * 64


def _document(**fields):
    document = {'format': 'playlist-recipe', 'version': 1, 'start_track_id': START, 'bpm': {'min': 98, 'max': 126.5},
                'length': {'tracks': 24}}
    document.update(fields)
    return {name: value for name, value in document.items() if value is not ...}


VALID = (
    _document(),
    _document(length={'minutes': 75}, harmonic_mixing={'enabled': False}, mood_hold='calm'),
    _document(length={'tracks': 10}, energy_plan=[{'shape': 'peak', 'energy_low': 0.1, 'energy_high': 0.9}]),
    _document(length=..., energy_plan=[{'shape': 'rise', 'tracks': 8, 'energy_high': 0.8},
                                       {'shape': 'steady', 'tracks': 4}, {'shape': 'dip', 'tracks': 8}]),
    _document(length=..., energy_plan=[{'shape': 'fall', 'minutes': 1000}, {'shape': 'rise', 'minutes': 440}]),
    _document(harmonic_mixing={'minimum_key_strength': 0}),
)

INVALID = (
    None, [], 'recipe', _document(format='m3u'), _document(version=2), _document(version=True), _document(tempo=1),
    _document(start_track_id=...), _document(start_track_id=' '), _document(bpm={'min': 1}),
    _document(bpm={'min': 2, 'max': 1}), _document(bpm={'min': float('nan'), 'max': 1}), _document(bpm={'min': '1', 'max': 2}),
    _document(length=...), _document(length={'tracks': 0}), _document(length={'tracks': 1001}),
    _document(length={'minutes': 1440.5}), _document(length={'tracks': 1, 'minutes': 1}), _document(length={'beats': 1}),
    _document(harmonic_mixing={'enabled': 1}), _document(harmonic_mixing={'minimum_key_strength': -0.1}),
    _document(mood_hold=''), _document(mood_hold=3), _document(energy_plan='rise'), _document(energy_plan=[{'shape': 'wave'}]),
    _document(energy_plan=[{'shape': 'rise', 'energy_low': 0.5, 'energy_high': 0.5}]),
    _document(energy_plan=[{'shape': 'rise'}, {'shape': 'fall'}]),
    _document(length=..., energy_plan=[{'shape': 'rise', 'tracks': 3}, {'shape': 'fall'}]),
    _document(energy_plan=[{'shape': 'rise', 'tracks': 3}]),
    _document(length=..., energy_plan=[{'shape': 'rise', 'tracks': 3}, {'shape': 'fall', 'minutes': 3}]),
    _document(length=..., energy_plan=[{'shape': 'rise', 'tracks': 600}, {'shape': 'fall', 'tracks': 401}]),
    _document(energy_plan=[{'shape': 'rise', 'colour': 'red'}]),
)


class SavedPlaylistRecipeContractTests(unittest.TestCase):
    def test_both_parsers_give_the_same_canonical_recipe(self):
        for document in VALID:
            with self.subTest(document=document):
                canonical = analyzer.parse_playlist_recipe(document).to_document()
                self.assertEqual(canonical, explorer.parse_saved_playlist_recipe(document).to_document())
                self.assertEqual(canonical, explorer.parse_saved_playlist_recipe(canonical).to_document())

    def test_both_parsers_reject_the_same_documents_with_the_same_message(self):
        for document in INVALID:
            with self.subTest(document=document):
                with self.assertRaises(analyzer.PlaylistRecipeError) as analyzer_error:
                    analyzer.parse_playlist_recipe(document)
                with self.assertRaises(explorer.SavedPlaylistRecipeError) as explorer_error:
                    explorer.parse_saved_playlist_recipe(document)
                self.assertEqual(str(analyzer_error.exception), str(explorer_error.exception))

    def test_both_accept_the_same_names(self):
        for name in ('Warm-up', '  padded  ', 'é' * 100):
            self.assertEqual(analyzer.playlist_recipe_name(name), explorer.saved_playlist_recipe_name(name))
        for name in ('', 'a' * 101, 'tab\there', None):
            with self.subTest(name=name):
                self.assertRaises(analyzer.PlaylistRecipeError, analyzer.playlist_recipe_name, name)
                self.assertRaises(explorer.SavedPlaylistRecipeError, explorer.saved_playlist_recipe_name, name)

    def test_the_explorer_reads_the_format_version_the_analyzer_writes(self):
        self.assertEqual((analyzer.FORMAT, analyzer.VERSION), (explorer.FORMAT, explorer.VERSION))


if __name__ == '__main__':
    unittest.main()
