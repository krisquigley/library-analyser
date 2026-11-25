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
        for bad in ('ten', '2.5'):
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
        with self.assertRaisesRegex(ValueError, 'Energy low and high must be numbers'):
            _recipe(start='a', length='5', arc='rise', energy_high='loud')

    def test_an_energy_range_needs_an_energy_arc(self):
        with self.assertRaisesRegex(ValueError, 'An energy range needs an energy arc'):
            _recipe(start='a', length='5', energy_low='0.2')

    def test_no_arc_and_no_mood_by_default_or_when_blank(self):
        for query in ({}, {'arc': 'none', 'mood': ''}, {'arc': ''}):
            with self.subTest(query=query):
                recipe = _recipe(start='a', length='5', **query)
                self.assertEqual(((), None), (recipe.energy_plan, recipe.mood_hold))



def _chain(**lists):
    return playlist_recipe_from_query({'start': ['a'], **lists})


class ChainedArcQueryTests(unittest.TestCase):
    # #137: arcs repeat in order; each one's range and length sit at the same place in their own lists.
    def test_arcs_repeat_in_order_with_their_own_ranges_and_lengths(self):
        recipe = _chain(arc=['rise', 'steady', 'fall'], arc_tracks=['4', '3', '5'], energy_low=['', '0.3', ''],
                        energy_high=['0.8', '', ''])

        self.assertEqual((EnergyArcRequest('rise', energy_high=0.8, tracks=4),
                          EnergyArcRequest('steady', energy_low=0.3, tracks=3),
                          EnergyArcRequest('fall', tracks=5)), recipe.energy_plan)
        self.assertEqual((None, None), _length(recipe), "the arcs set the playlist's length")

    def test_arcs_can_last_minutes(self):
        recipe = _chain(arc=['rise', 'fall'], arc_minutes=['20', '12.5'])

        self.assertEqual((EnergyArcRequest('rise', minutes=20.0), EnergyArcRequest('fall', minutes=12.5)),
                         recipe.energy_plan)

    def test_an_arc_length_that_cannot_be_read_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'An arc length must be a whole number of tracks, at least 1'):
            _chain(arc=['rise'], arc_tracks=['2.5'])
        with self.assertRaisesRegex(ValueError, 'An arc length must be a positive number of minutes'):
            _chain(arc=['rise'], arc_minutes=['long'])

    def test_each_arc_needs_its_own_value_in_every_list_it_uses(self):
        for lists in ({'arc_tracks': ['4']}, {'energy_low': ['0.2', '0.3', '0.4']}, {'arc_minutes': ['5', '', '7']}):
            with self.subTest(lists=lists):
                with self.assertRaisesRegex(ValueError, 'Give each arc its own'):
                    _chain(arc=['rise', 'fall'], **lists)

    def test_every_arc_in_a_chain_needs_a_shape(self):
        with self.assertRaisesRegex(ValueError, 'Each arc in a chain needs a shape'):
            _chain(arc=['rise', 'none'], arc_tracks=['3', '3'])

    def test_an_arc_length_needs_an_energy_arc(self):
        with self.assertRaisesRegex(ValueError, 'An arc length needs an energy arc'):
            _chain(arc_tracks=['3'], length=['5'])

    def test_a_blank_single_value_is_unset_as_if_it_were_left_out(self):
        recipe = playlist_recipe_from_query({'start_track_id': [''], 'start': ['a'], 'length': [''],
                                             'duration_minutes': ['60'], 'mood': [''], 'arc': ['']})

        self.assertEqual(('a', None, '60', (), None), (recipe.start_track_id, recipe.length, recipe.duration_minutes,
                                                     recipe.energy_plan, recipe.mood_hold))

def _length(recipe):
    return recipe.length, recipe.duration_minutes


if __name__ == '__main__':
    unittest.main()
