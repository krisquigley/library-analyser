"""Issue #135: the M3U request's query string becomes a PlaylistRecipe."""
import unittest

from music_explorer.application.dto.playlists import EnergyArcRequest, PlaylistRecipe
from music_explorer.interface_adapters.playlist_recipe_query import playlist_recipe_from_query


def _recipe(**query):
    return playlist_recipe_from_query({name: [value] for name, value in query.items()})


class PlaylistRecipeQueryTests(unittest.TestCase):
    def test_a_track_count_playlist_with_the_defaults(self):
        self.assertEqual(PlaylistRecipe(start_track_id='a', bpm_min='100', bpm_max='130', length=20),
                         _recipe(start_track_id='a', bpm_min='100', bpm_max='130', length='20'))

    def test_start_and_count_are_accepted_as_older_names(self):
        recipe = _recipe(start='a', bpm_min='100', bpm_max='130', count='5')

        self.assertEqual(('a', 5), (recipe.start_track_id, recipe.length))

    def test_a_duration_playlist_has_no_track_count_unless_one_is_given(self):
        self.assertEqual((None, '60'), _length(_recipe(start='a', duration_minutes='60')))
        self.assertEqual((40, '60'), _length(_recipe(start='a', duration_minutes='60', length='40')))

    def test_a_missing_length_is_zero_tracks_so_the_use_case_rejects_it(self):
        self.assertEqual((0, None), _length(_recipe(start='a')))

    def test_a_length_that_is_not_a_whole_number_is_rejected(self):
        for bad in ('ten', '2.5', ''):
            with self.subTest(length=bad):
                with self.assertRaisesRegex(ValueError, 'Playlist length must be positive and between 1 and 1000'):
                    _recipe(start='a', length=bad)

    def test_harmonic_mixing_switch_and_minimum_key_strength(self):
        self.assertFalse(_recipe(start='a', length='5', harmonic='off').harmonic_mixing)
        self.assertEqual(0.8, _recipe(start='a', length='5', min_key_strength='0.8').minimum_key_strength)
        with self.assertRaisesRegex(ValueError, 'Harmonic mixing must be on or off'):
            _recipe(start='a', length='5', harmonic='maybe')
        with self.assertRaisesRegex(ValueError, 'Minimum key strength must be between 0.0 and 1.0'):
            _recipe(start='a', length='5', min_key_strength='strong')

    def test_the_minimum_key_strength_is_ignored_while_harmonic_mixing_is_off(self):
        recipe = _recipe(start='a', length='5', harmonic='off', min_key_strength='strong')

        self.assertEqual((False, 0.5), (recipe.harmonic_mixing, recipe.minimum_key_strength))

    def test_an_energy_arc_and_a_mood_hold(self):
        recipe = _recipe(start='a', length='5', arc='rise', mood='calm')

        self.assertEqual(((EnergyArcRequest('rise'),), 'calm'), (recipe.energy_plan, recipe.mood_hold))

    def test_an_energy_range_for_the_arc(self):
        recipe = _recipe(start='a', length='5', arc='rise', energy_low='0.2', energy_high='0.75')

        self.assertEqual((EnergyArcRequest('rise', energy_low=0.2, energy_high=0.75),), recipe.energy_plan)

    def test_a_blank_end_of_the_range_is_unset(self):
        recipe = _recipe(start='a', length='5', arc='rise', energy_low='', energy_high='0.75')

        self.assertEqual((EnergyArcRequest('rise', energy_high=0.75),), recipe.energy_plan)

    def test_an_energy_range_that_is_not_a_number_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'Energy low and high must be between 0.0 and 1.0'):
            _recipe(start='a', length='5', arc='rise', energy_high='loud')

    def test_an_energy_range_needs_an_energy_arc(self):
        with self.assertRaisesRegex(ValueError, 'An energy range needs an energy arc'):
            _recipe(start='a', length='5', energy_low='0.2')

    def test_no_arc_and_no_mood_by_default_or_when_blank(self):
        for query in ({}, {'arc': 'none', 'mood': ''}, {'arc': ''}):
            with self.subTest(query=query):
                recipe = _recipe(start='a', length='5', **query)
                self.assertEqual(((), None), (recipe.energy_plan, recipe.mood_hold))


def _length(recipe):
    return recipe.length, recipe.duration_minutes


if __name__ == '__main__':
    unittest.main()
