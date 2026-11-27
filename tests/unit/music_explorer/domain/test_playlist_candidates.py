"""The candidate tracks as the playlist walk sees them (#120, #122, #123)."""
from dataclasses import dataclass
import unittest

from music_explorer.domain.harmonic_mixing import HarmonicMixing
from music_explorer.domain.playlist_candidates import usable_energy_and_mood, usable_valence, walk_track


@dataclass(frozen=True)
class _Track:
    track_id: str = 'a'
    bpm: float = 120.0
    artist: str = 'Artist'
    duration_seconds: float = 200.0
    key: str = 'C'
    scale: str = 'major'
    key_strength: float = 0.9
    manual_overrides: tuple = ()


@dataclass(frozen=True)
class _Evidence:
    arousal: object
    mood_score: object
    valence: object = None


class WalkTrackTests(unittest.TestCase):
    def test_a_strong_detected_key_is_used_while_harmonic_mixing_is_on(self):
        track = walk_track(_Track(), HarmonicMixing())
        self.assertEqual(('a', 'Artist', 200.0, 120.0), (track.track_id, track.artist, track.duration_seconds, track.bpm))
        self.assertIsNotNone(track.key)

    def test_no_key_without_harmonic_mixing_or_with_a_manual_key(self):
        self.assertIsNone(walk_track(_Track(), None).key)
        self.assertIsNone(walk_track(_Track(manual_overrides=('key',)), HarmonicMixing()).key)


class UsableEvidenceTests(unittest.TestCase):
    def test_a_manual_energy_or_mood_leaves_that_detection_unknown(self):
        candidates = {'a': _Track('a'), 'b': _Track('b', manual_overrides=('energy',)),
                      'c': _Track('c', manual_overrides=('mood',)), 'd': _Track('d')}
        evidence = {'a': _Evidence(0.4, 0.6), 'b': _Evidence(0.5, 0.7), 'c': _Evidence(0.6, 0.8),
                    'd': _Evidence(None, None)}

        self.assertEqual(({'a': 0.4, 'c': 0.6}, {'a': 0.6, 'b': 0.7}), usable_energy_and_mood(candidates, evidence))

    def test_294_valence_is_known_where_energy_is_detected_and_not_overridden(self):
        candidates = {'a': _Track('a'), 'b': _Track('b', manual_overrides=('energy',)), 'c': _Track('c'), 'd': _Track('d')}
        evidence = {'a': _Evidence(0.4, None, 5.5), 'b': _Evidence(0.5, None, 6.0), 'c': _Evidence(0.6, None)}
        self.assertEqual({'a': 5.5}, usable_valence(candidates, evidence))


if __name__ == '__main__':
    unittest.main()
