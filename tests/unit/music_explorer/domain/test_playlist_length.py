"""How long a playlist is (#58, #121, #137)."""
from dataclasses import dataclass
import unittest

from music_explorer.domain.playlist_length import goal_and_arc_lengths, playlist_goal, shortfall_warning
from music_explorer.domain.playlist_walk import DurationGoal, TrackCountGoal


@dataclass(frozen=True)
class _Arc:
    tracks: object = None
    minutes: object = None


class PlaylistLengthTests(unittest.TestCase):
    def test_a_count_or_a_duration_capped_at_the_track_limit(self):
        self.assertEqual(TrackCountGoal(20), playlist_goal(20, None))
        self.assertEqual(DurationGoal(3600.0, 1000), playlist_goal(None, '60'))
        self.assertEqual(DurationGoal(3600.0, 40), playlist_goal(40, '60'))

    def test_without_arc_lengths_one_arc_spans_the_playlist(self):
        self.assertEqual((TrackCountGoal(12), (12,)), goal_and_arc_lengths((_Arc(),), 12, None))
        self.assertEqual((DurationGoal(1800.0, 1000), (1800.0,)), goal_and_arc_lengths((_Arc(),), None, 30))
        self.assertEqual((TrackCountGoal(5), ()), goal_and_arc_lengths((), 5, None))

    def test_arc_lengths_add_up_to_the_playlist(self):
        self.assertEqual((TrackCountGoal(7), (3, 4)), goal_and_arc_lengths((_Arc(tracks=3), _Arc(tracks=4)), None, None))
        self.assertEqual((DurationGoal(1500.0, 1000), (600.0, 900.0)),
                         goal_and_arc_lengths((_Arc(minutes=10), _Arc(minutes=15)), None, None))

    def test_a_shortfall_is_explained_in_the_playlist_s_unit(self):
        self.assertIn('requested duration', shortfall_warning(DurationGoal(60.0, 10)))
        self.assertIn('dead end', shortfall_warning(TrackCountGoal(10)))


if __name__ == '__main__':
    unittest.main()
