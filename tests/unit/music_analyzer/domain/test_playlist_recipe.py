"""Issue #139: a saved playlist recipe is a versioned document, checked before the analyzer stores it."""
import unittest

from music_analyzer.domain.playlist_recipe import (
    PlaylistRecipeError, parse_playlist_recipe, playlist_recipe_name)


def _recipe(**fields):
    document = {'format': 'playlist-recipe', 'version': 1, 'start_track_id': 'sha256:abc', 'bpm': {'min': 100, 'max': 130},
                'length': {'tracks': 20}}
    document.update(fields)
    return {name: value for name, value in document.items() if value is not ...}


class ValidRecipeTests(unittest.TestCase):
    def test_a_minimal_recipe_gets_the_defaults_and_a_canonical_form(self):
        recipe = parse_playlist_recipe(_recipe())

        self.assertEqual({'format': 'playlist-recipe', 'version': 1, 'start_track_id': 'sha256:abc',
                          'bpm': {'min': 100.0, 'max': 130.0}, 'length': {'tracks': 20},
                          'harmonic_mixing': {'enabled': True, 'minimum_key_strength': 0.5}, 'energy_plan': [],
                          'mood_hold': None}, recipe.to_document())

    def test_a_full_recipe_round_trips(self):
        document = _recipe(length=..., harmonic_mixing={'enabled': False, 'minimum_key_strength': 0.7}, mood_hold='calm',
                           energy_plan=[{'shape': 'rise', 'minutes': 20, 'energy_low': None, 'energy_high': 0.8},
                                        {'shape': 'dip', 'minutes': 12.5, 'energy_low': 0.2, 'energy_high': None}])
        recipe = parse_playlist_recipe(document)

        self.assertEqual(recipe, parse_playlist_recipe(recipe.to_document()))
        self.assertEqual([{'shape': 'rise', 'minutes': 20.0, 'energy_low': None, 'energy_high': 0.8},
                          {'shape': 'dip', 'minutes': 12.5, 'energy_low': 0.2, 'energy_high': None}],
                         recipe.to_document()['energy_plan'])
        self.assertNotIn('length', recipe.to_document(), "the arcs set the playlist's length")

    def test_a_duration_playlist_and_one_arc_spanning_it(self):
        recipe = parse_playlist_recipe(_recipe(length={'minutes': 60}, energy_plan=[{'shape': 'peak'}]))

        self.assertEqual(({'minutes': 60.0}, [{'shape': 'peak', 'energy_low': None, 'energy_high': None}]),
                         (recipe.to_document()['length'], recipe.to_document()['energy_plan']))


class InvalidRecipeTests(unittest.TestCase):
    def assertRejected(self, message, document):
        with self.assertRaisesRegex(PlaylistRecipeError, message):
            parse_playlist_recipe(document)

    def test_only_this_format_and_version(self):
        self.assertRejected('not a playlist recipe', _recipe(format='m3u'))
        self.assertRejected('version 2 is not supported; only version 1 can be read', _recipe(version=2))
        self.assertRejected('version True is not supported', _recipe(version=True))
        self.assertRejected('must be a JSON object', ['not', 'an', 'object'])

    def test_unknown_or_missing_fields(self):
        self.assertRejected('Unknown recipe field: tempo', _recipe(tempo=120))
        self.assertRejected('Unknown recipe field: bpm.median', _recipe(bpm={'min': 1, 'max': 2, 'median': 1.5}))
        self.assertRejected('Recipe needs start_track_id', _recipe(start_track_id=...))
        self.assertRejected('Recipe needs bpm.max', _recipe(bpm={'min': 100}))

    def test_values_of_the_wrong_kind_are_never_coerced(self):
        for fields, message in (({'start_track_id': ''}, 'start_track_id must be non-empty text'),
                                ({'bpm': {'min': '100', 'max': 130}}, 'bpm.min must be a finite number'),
                                ({'bpm': {'min': True, 'max': 130}}, 'bpm.min must be a finite number'),
                                ({'bpm': {'min': 140, 'max': 130}}, 'bpm.min must not be above bpm.max'),
                                ({'length': {'tracks': 2.5}}, 'length.tracks must be a whole number from 1 to 1000'),
                                ({'length': {'minutes': 0}}, 'length.minutes must be above 0 and at most 1440'),
                                ({'length': {'tracks': 5, 'minutes': 5}}, 'length is tracks or minutes, not both'),
                                ({'harmonic_mixing': {'enabled': 'yes'}}, 'harmonic_mixing.enabled must be true or false'),
                                ({'harmonic_mixing': {'minimum_key_strength': 1.5}},
                                 'harmonic_mixing.minimum_key_strength must be between 0 and 1'),
                                ({'mood_hold': ''}, 'mood_hold must be non-empty text or null'),
                                ({'energy_plan': {'shape': 'rise'}}, 'energy_plan must be a list of arcs')):
            with self.subTest(fields=fields):
                self.assertRejected(message, _recipe(**fields))

    def test_each_arc_is_checked_and_named_by_its_place(self):
        for arc, message in (({'shape': 'wave'}, r'energy_plan\[0\].shape must be steady, rise, fall, peak or dip'),
                             ({'shape': 'rise', 'energy_low': 0.8, 'energy_high': 0.2},
                              r'energy_plan\[0\].energy_low must be below its energy_high'),
                             ({'shape': 'rise', 'energy_low': 0.5, 'energy_high': 0.5},
                              r'energy_plan\[0\].energy_low must be below its energy_high'),
                             ({'shape': 'rise', 'energy_high': 2}, r'energy_plan\[0\].energy_high must be between 0 and 1'),
                             ({'shape': 'rise', 'colour': 'red'}, r'Unknown recipe field: energy_plan\[0\].colour')):
            with self.subTest(arc=arc):
                self.assertRejected(message, _recipe(energy_plan=[arc]))

    def test_the_length_comes_from_the_playlist_or_from_every_arc_in_one_unit(self):
        rise, fall = {'shape': 'rise'}, {'shape': 'fall'}
        self.assertRejected('Recipe needs a length, or a length on every arc', _recipe(length=...))
        self.assertRejected('Each arc in a chain needs a length', _recipe(energy_plan=[rise, fall]))
        self.assertRejected('Each arc in a chain needs a length', _recipe(length=..., energy_plan=[{**rise, 'tracks': 3}, fall]))
        self.assertRejected("leave the recipe's length out", _recipe(energy_plan=[{**rise, 'tracks': 3}]))
        self.assertRejected('in the same unit', _recipe(length=..., energy_plan=[{**rise, 'tracks': 3}, {**fall, 'minutes': 4}]))
        self.assertRejected('in the same unit', _recipe(length=..., energy_plan=[{**rise, 'tracks': 3, 'minutes': 4}]))
        self.assertRejected('at most 1000 tracks', _recipe(length=..., energy_plan=[{**rise, 'tracks': 600}, {**fall, 'tracks': 401}]))
        self.assertRejected('at most 1440 minutes', _recipe(length=..., energy_plan=[{**rise, 'minutes': 1000},
                                                                                      {**fall, 'minutes': 441}]))


class LimitTests(unittest.TestCase):
    def test_a_chain_may_reach_the_limits_exactly(self):
        for arcs in ([{'shape': 'rise', 'tracks': 600}, {'shape': 'fall', 'tracks': 400}],
                     [{'shape': 'rise', 'minutes': 1000}, {'shape': 'fall', 'minutes': 440}]):
            with self.subTest(arcs=arcs):
                self.assertEqual(len(arcs), len(parse_playlist_recipe(_recipe(length=..., energy_plan=arcs)).energy_plan))

    def test_an_arc_needs_some_minutes(self):
        with self.assertRaisesRegex(PlaylistRecipeError, r'energy_plan\[0\].minutes must be above 0'):
            parse_playlist_recipe(_recipe(length=..., energy_plan=[{'shape': 'rise', 'minutes': 0}]))


class RecipeNameTests(unittest.TestCase):
    def test_a_name_is_trimmed_non_empty_printable_text_of_at_most_100_characters(self):
        self.assertEqual('Friday warm-up', playlist_recipe_name('  Friday warm-up '))
        for name in ('', '   ', 'a' * 101, 'tab\there', None):
            with self.subTest(name=name):
                with self.assertRaisesRegex(PlaylistRecipeError, 'A recipe name is 1 to 100 printable characters'):
                    playlist_recipe_name(name)


if __name__ == '__main__':
    unittest.main()
