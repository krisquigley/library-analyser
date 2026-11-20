"""Issue #137: a playlist follows a chain of energy arcs, each with its own length."""
from itertools import combinations
import unittest

from music_explorer.application.dto.playlists import EnergyArcRequest, PlaylistRecipe
from music_explorer.application.use_cases.playlists import GenerateBpmGraphM3UPlaylist
from tests.unit.application.test_m3u_playlist_generation import _FakePlaylistRepository, _PlayableTrack, _edge


def _even_library(seconds=180.0):
    # t0..t9 have energy levels 0, 1/9 ... 1; every pair is equally related, so only the plan steers the walk.
    tracks = tuple(_PlayableTrack(f't{i}', 120, f'/library/t{i}.flac', arousal=float(i), duration_seconds=seconds)
                   for i in range(10))
    edges = tuple(_edge(a.track_id, b.track_id, 0.5) for a, b in combinations(tracks, 2))
    return _FakePlaylistRepository(tracks=tracks, edges=edges)


def _generate(repo, *arcs, **recipe):
    return GenerateBpmGraphM3UPlaylist(repo).execute(PlaylistRecipe(
        start_track_id='t4', bpm_min=100, bpm_max=130, harmonic_mixing=False, energy_plan=arcs, **recipe))


class ChainedArcPlaylistTests(unittest.TestCase):
    def test_a_three_arc_chain_rises_falls_and_rises_again_for_the_sum_of_its_lengths(self):
        result = _generate(_even_library(), EnergyArcRequest('rise', tracks=3), EnergyArcRequest('fall', tracks=3),
                           EnergyArcRequest('rise', tracks=3))

        self.assertEqual(('t4', 't6', 't8', 't5', 't3', 't1', 't2', 't7', 't9'), result.track_ids)
        self.assertIsNone(result.warning)

    def test_each_arc_keeps_its_own_energy_range(self):
        result = _generate(_even_library(), EnergyArcRequest('rise', energy_high=0.6, tracks=2),
                           EnergyArcRequest('fall', energy_low=0.3, tracks=2))

        self.assertEqual(('t4', 't5', 't3', 't2'), result.track_ids)

    def test_by_minutes_the_playlist_lasts_the_sum_of_its_arcs(self):
        result = _generate(_even_library(seconds=60.0), EnergyArcRequest('rise', minutes=3),
                           EnergyArcRequest('fall', minutes=2), EnergyArcRequest('steady', minutes=1))

        self.assertEqual(6, len(result.track_ids))
        self.assertIsNone(result.warning)

    def test_a_single_arc_without_a_length_still_spans_the_playlist(self):
        result = _generate(_even_library(), EnergyArcRequest('rise'), length=3)

        self.assertEqual(('t4', 't6', 't8'), result.track_ids)


class ChainedArcRecipeTests(unittest.TestCase):
    def assertRejected(self, message, *arcs, **recipe):
        repo = _even_library()
        with self.assertRaisesRegex(ValueError, message):
            _generate(repo, *arcs, **recipe)
        self.assertEqual((0, []), (repo.track_reads, repo.mood_evidence_reads), 'rejected before any read')

    def test_every_arc_in_a_chain_needs_a_length(self):
        self.assertRejected('Each arc in a chain needs a length', EnergyArcRequest('rise'), EnergyArcRequest('fall'),
                            length=10)
        self.assertRejected('Each arc in a chain needs a length', EnergyArcRequest('rise', tracks=3),
                            EnergyArcRequest('fall'))

    def test_the_arcs_share_one_unit(self):
        self.assertRejected('the same unit', EnergyArcRequest('rise', tracks=3), EnergyArcRequest('fall', minutes=5))
        self.assertRejected('the same unit', EnergyArcRequest('rise', tracks=3, minutes=5))

    def test_the_arcs_set_the_playlist_length(self):
        for recipe in ({'length': 9}, {'duration_minutes': 30}):
            with self.subTest(recipe=recipe):
                self.assertRejected("the playlist's length is the sum of its arcs",
                                    EnergyArcRequest('rise', tracks=3), **recipe)

    def test_an_arc_lasts_a_whole_number_of_tracks_or_a_positive_number_of_minutes(self):
        for tracks in (0, 2.5, True, '3'):
            with self.subTest(tracks=tracks):
                self.assertRejected('An arc length must be a whole number of tracks, at least 1',
                                    EnergyArcRequest('rise', tracks=tracks))
        for minutes in (0, -1, float('nan'), float('inf'), 'long'):
            with self.subTest(minutes=minutes):
                self.assertRejected('An arc length must be a positive number of minutes',
                                    EnergyArcRequest('rise', minutes=minutes))

    def test_the_sum_of_the_arcs_stays_within_the_playlist_limits(self):
        self.assertRejected('Playlist length must be positive and between 1 and 1000',
                            EnergyArcRequest('rise', tracks=600), EnergyArcRequest('fall', tracks=401))
        self.assertRejected('at most 1440 minutes', EnergyArcRequest('rise', minutes=1000),
                            EnergyArcRequest('fall', minutes=441))


if __name__ == '__main__':
    unittest.main()
