"""Issue #138: see a playlist, track by track and transition by transition, before downloading it."""
import unittest
from dataclasses import replace

from music_explorer.application.dto.playlists import EnergyArcRequest, PlaylistRecipe
from music_explorer.application.use_cases.download_playlist.download_playlist import GenerateBpmGraphM3UPlaylist
from music_explorer.application.use_cases.preview_playlist.preview_playlist import PreviewPlaylist
from tests.unit.application.test_m3u_playlist_generation import _FakePlaylistRepository, _PlayableTrack, _edge


def _library(changes=None):
    changes = changes or {}
    return _FakePlaylistRepository(
        tracks=tuple(replace(track, **changes.get(track.track_id, {})) for track in (_PlayableTrack('a', 120, '/library/a.flac', title='Opening', artist='First', key='C', scale='major',
                               key_strength=0.9, arousal=2.0),
                _PlayableTrack('b', 124, '/library/b.flac', title='Middle', artist='Second', key='G', scale='major',
                               key_strength=0.9, arousal=5.0),
                _PlayableTrack('c', 135, '/library/c.flac', title='Late', artist='Third', key='F#', scale='major',
                               key_strength=0.2, arousal=8.0),
                _PlayableTrack('d', 121, '/library/d.flac', manual_overrides=('energy',), arousal=9.0))),
        edges=(_edge('a', 'b', 0.9), _edge('b', 'c', 0.8), _edge('a', 'd', 0.7)))


def _recipe(**options):
    return PlaylistRecipe(**{'start_track_id': 'a', 'bpm_min': 100, 'bpm_max': 140, 'length': 3, **options})


class PreviewPlaylistTests(unittest.TestCase):
    def test_the_preview_lists_the_same_tracks_as_the_download_for_the_same_recipe(self):
        for options in ({}, {'energy_plan': (EnergyArcRequest('rise'),)}, {'harmonic_mixing': False},
                        {'length': None, 'duration_minutes': 9}):
            with self.subTest(options=options):
                download = GenerateBpmGraphM3UPlaylist(_library()).execute(_recipe(**options))
                preview = PreviewPlaylist(_library()).execute(_recipe(**options))
                self.assertEqual(download.track_ids, tuple(track.track_id for track in preview.tracks))
                self.assertEqual((download.warning, download.warning is None), (preview.warning, preview.complete))

    def test_each_track_shows_what_it_is_and_its_energy(self):
        tracks = PreviewPlaylist(_library()).execute(_recipe()).tracks

        self.assertEqual([('a', 'Opening', 'First', 120, 'C major', '8B'), ('b', 'Middle', 'Second', 124, 'G major', '9B'),
                          ('c', 'Late', 'Third', 135, 'F# major', '2B')],
                         [(t.track_id, t.title, t.artist, t.bpm, t.key, t.camelot) for t in tracks])
        self.assertEqual([2.0, 5.0, 8.0], [track.arousal for track in tracks], 'raw arousal, as the graph shows it (#265)')
        self.assertEqual([None, None, None], [track.energy_target for track in tracks], 'no arc, no target')

    def test_each_track_shows_its_length_where_the_audio_file_gave_one(self):
        # Issue #257.
        tracks = PreviewPlaylist(_library({'b': {'duration_seconds': 241.5}, 'c': {'duration_seconds': None}})).execute(_recipe()).tracks
        self.assertEqual([180.0, 241.5, None], [track.duration_seconds for track in tracks])

    def test_with_an_arc_each_track_shows_the_target_it_was_chosen_for(self):
        tracks = PreviewPlaylist(_library()).execute(_recipe(energy_plan=(EnergyArcRequest('rise'),))).tracks

        # #265: in raw arousal, from a (2) towards the eligible tracks' 90th percentile (7.4).
        for actual, expected in zip([track.energy_target for track in tracks], (2.0, 4.7, 7.4)):
            self.assertAlmostEqual(expected, actual)

    def test_a_manual_energy_leaves_the_track_s_energy_unknown(self):
        repo = _FakePlaylistRepository(tracks=_library()._tracks, edges=(_edge('a', 'd', 0.9),))
        track = PreviewPlaylist(repo).execute(_recipe(length=2)).tracks[1]

        self.assertEqual(('d', None, None, None), (track.track_id, track.arousal, track.key, track.camelot))

    def test_each_transition_shows_its_key_compatibility_and_bpm_step(self):
        transitions = PreviewPlaylist(_library()).execute(_recipe()).transitions

        self.assertEqual([('a', 'b', True, True, 4.0), ('b', 'c', None, False, 11.0)],
                         [(t.from_track_id, t.to_track_id, t.key_compatible, t.bpm_step_smooth, t.bpm_change)
                          for t in transitions])

    def test_a_short_walk_is_marked_incomplete_with_the_warning(self):
        preview = PreviewPlaylist(_library()).execute(_recipe(length=6))

        self.assertFalse(preview.complete)
        self.assertIn('dead end', preview.warning)

    def test_an_invalid_recipe_is_rejected_before_anything_is_read(self):
        repo = _library()
        with self.assertRaisesRegex(ValueError, 'bpm bounds must be ordered'):
            PreviewPlaylist(repo).execute(PlaylistRecipe(start_track_id='a', bpm_min=140, bpm_max=100, length=3))
        self.assertEqual((0, [], []), (repo.track_reads, repo.mood_evidence_reads, repo.edge_reads))


if __name__ == '__main__':
    unittest.main()
