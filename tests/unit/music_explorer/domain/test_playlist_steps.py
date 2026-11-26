"""#138, #287: how one track steps into the next in a playlist: its key and its tempo."""
import unittest

from music_explorer.domain.harmonic_mixing import HarmonicMixing, MusicalKey
from music_explorer.domain.playlist_steps import PlaylistStep, playlist_step
from music_explorer.domain.playlist_walk import WalkTrack

C_MAJOR, G_MAJOR, F_SHARP_MAJOR = (MusicalKey.parse(tonic, 'major') for tonic in ('C', 'G', 'F#'))


def track(bpm, key=None):
    return WalkTrack('t', bpm=bpm, key=key)


class PlaylistStepTest(unittest.TestCase):
    def test_a_compatible_key_and_a_small_tempo_step(self):
        self.assertEqual(playlist_step(track(120.0, C_MAJOR), track(124.0, G_MAJOR), HarmonicMixing()),
                         PlaylistStep(key_compatible=True, bpm_step_smooth=True, bpm_change=4.0))

    def test_a_key_clash_and_a_tempo_jump(self):
        self.assertEqual(playlist_step(track(120.0, C_MAJOR), track(100.0, F_SHARP_MAJOR), HarmonicMixing()),
                         PlaylistStep(key_compatible=False, bpm_step_smooth=False, bpm_change=-20.0))

    def test_what_cannot_be_told_is_none(self):
        self.assertEqual(playlist_step(track(120.0, C_MAJOR), track(None), HarmonicMixing()),
                         PlaylistStep(key_compatible=None, bpm_step_smooth=None, bpm_change=None))


if __name__ == '__main__':
    unittest.main()
