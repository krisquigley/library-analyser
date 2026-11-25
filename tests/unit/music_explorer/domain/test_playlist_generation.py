"""Issue #138: one generation rule for the M3U download and the preview of the same recipe."""
from dataclasses import dataclass
import unittest

from music_explorer.domain.arousal_scale import ArousalScale
from music_explorer.domain.playlist_generation import PlaylistRules, generate_walk


@dataclass(frozen=True)
class _Track:
    track_id: str
    bpm: float = 120.0
    path: str = '/library/x.flac'
    artist: str = ''
    duration_seconds: float | None = 180.0
    manual_overrides: tuple = ()
    key: str | None = None
    scale: str | None = None
    key_strength: float | None = None


@dataclass(frozen=True)
class _Edge:
    a: str
    b: str
    score: float


@dataclass(frozen=True)
class _Evidence:
    arousal: object = None
    mood_score: object = None


@dataclass(frozen=True)
class _Arc:
    shape: str
    energy_low: object = None
    energy_high: object = None
    tracks: object = None
    minutes: object = None


def _rules(**options):
    recipe = dict(start_track_id='a', bpm_min=100, bpm_max=130, length=3, duration_minutes=None, harmonic_mixing=False,
                  minimum_key_strength=0.5, energy_plan=(), mood_hold=None)
    recipe.update(options)
    return PlaylistRules.of(**recipe)


TRACKS = (_Track('a'), _Track('b'), _Track('c'), _Track('slow', bpm=80))
EDGES = (_Edge('a', 'b', 0.9), _Edge('b', 'c', 0.8), _Edge('a', 'slow', 0.99))


class PlaylistRulesTests(unittest.TestCase):
    def test_every_rule_is_checked_before_anything_is_read(self):
        for options, message in (({'minimum_key_strength': 2, 'harmonic_mixing': True}, 'Minimum key strength'),
                                 ({'bpm_min': None}, 'BPM minimum bound is required'),
                                 ({'length': 0}, 'Playlist length must be positive'),
                                 ({'start_track_id': ''}, 'start track is required'),
                                 ({'energy_plan': (_Arc('wave'),)}, 'steady, rise, fall, peak or dip'),
                                 ({'energy_plan': (_Arc('rise', energy_low=0.9, energy_high=0.1),)}, 'below energy high')):
            with self.subTest(options=options):
                with self.assertRaisesRegex(ValueError, message):
                    _rules(**options)

    def test_evidence_is_needed_only_for_an_arc_or_a_mood_hold(self):
        self.assertEqual([False, True, True], [_rules(**options).needs_evidence for options in (
            {}, {'energy_plan': (_Arc('rise'),)}, {'mood_hold': 'calm'})])


class GenerateWalkTests(unittest.TestCase):
    def test_the_walk_follows_eligible_related_tracks(self):
        generated = generate_walk(_rules(), TRACKS, EDGES, {})

        self.assertEqual((('a', 'b', 'c'), True, None), (generated.track_ids, generated.complete, generated.warning))
        self.assertEqual({'a', 'b', 'c'}, set(generated.candidates))
        self.assertIsNone(generated.plan)

    def test_a_short_walk_is_warned_about(self):
        generated = generate_walk(_rules(length=5), TRACKS, EDGES, {})

        self.assertFalse(generated.complete)
        self.assertIn('dead end', generated.warning)

    def test_the_start_track_says_why_it_cannot_open_the_playlist(self):
        for start, message in (('slow', 'start track BPM is outside requested range'),
                               ('missing', 'start track is not playable or available')):
            with self.subTest(start=start):
                with self.assertRaisesRegex(ValueError, message):
                    generate_walk(_rules(start_track_id=start), TRACKS, EDGES, {})

    def test_a_duration_playlist_needs_a_start_track_with_a_duration(self):
        tracks = (_Track('a', duration_seconds=None), _Track('b'))
        with self.assertRaisesRegex(ValueError, 'no verified duration'):
            generate_walk(_rules(length=None, duration_minutes=10), tracks, EDGES, {})

    def test_an_arc_plans_on_the_candidates_energy_and_a_mood_hold_needs_a_scored_track(self):
        evidence = {'a': _Evidence(arousal=1.0), 'b': _Evidence(arousal=2.0), 'c': _Evidence(arousal=3.0)}
        generated = generate_walk(_rules(energy_plan=(_Arc('rise'),)), TRACKS, EDGES, evidence)

        self.assertEqual({'a': 1.0, 'b': 2.0, 'c': 3.0}, dict(generated.plan.levels), 'raw arousal (#265)')
        self.assertEqual(ArousalScale.of([1.0, 2.0, 3.0]), generated.plan.scale, "the eligible tracks' scale")
        with self.assertRaisesRegex(ValueError, "No eligible track has a score for the mood 'calm'"):
            generate_walk(_rules(mood_hold='calm'), TRACKS, EDGES, evidence)


if __name__ == '__main__':
    unittest.main()
