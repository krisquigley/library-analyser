"""Issue #121: the playlist walk searches past dead ends instead of stopping at them."""
import unittest

from music_explorer.domain.playlist_walk import DurationGoal, TrackCountGoal, WalkTrack, walk_playlist


def related(*edges):
    """Undirected related-track lists, as the use case builds them from graph edges."""
    lists = {}
    for a, b, score in edges:
        lists.setdefault(a, []).append((b, score))
        lists.setdefault(b, []).append((a, score))
    return lists


def tracks(*ids, artists=None, durations=None):
    artists, durations = artists or {}, durations or {}
    return {i: WalkTrack(i, artists.get(i, ''), durations.get(i, 180.0)) for i in ids}


class PlaylistWalkTests(unittest.TestCase):
    def test_backtracks_out_of_a_dead_end_to_reach_the_requested_length(self):
        walk = walk_playlist('a', tracks('a', 'b', 'c', 'd'),
                             related(('a', 'b', 0.9), ('a', 'c', 0.5), ('c', 'd', 0.5)), TrackCountGoal(3))

        self.assertEqual(('a', 'c', 'd'), walk.track_ids)
        self.assertTrue(walk.complete)

    def test_follows_the_strongest_relations_when_they_lead_to_a_full_playlist(self):
        walk = walk_playlist('a', tracks('a', 'b', 'c', 'd'),
                             related(('a', 'b', 0.9), ('a', 'c', 0.9), ('b', 'd', 0.95)), TrackCountGoal(3))

        self.assertEqual(('a', 'b', 'd'), walk.track_ids, 'score first, then track id; same as before #121')

    def test_never_repeats_a_track(self):
        walk = walk_playlist('a', tracks('a', 'b'), related(('a', 'b', 1.0)), TrackCountGoal(5))

        self.assertEqual(('a', 'b'), walk.track_ids)
        self.assertFalse(walk.complete)

    def test_no_same_artist_back_to_back_ignoring_case_and_spacing(self):
        library = tracks('a', 'b', 'c', artists={'a': 'Boards of Canada', 'b': ' boards of canada', 'c': 'Autechre'})

        walk = walk_playlist('a', library, related(('a', 'b', 0.9), ('a', 'c', 0.5)), TrackCountGoal(2))

        self.assertEqual(('a', 'c'), walk.track_ids)

    def test_same_artist_may_return_after_another_artist(self):
        library = tracks('a', 'b', 'c', artists={'a': 'X', 'b': 'Y', 'c': 'X'})

        walk = walk_playlist('a', library, related(('a', 'b', 0.9), ('b', 'c', 0.9)), TrackCountGoal(3))

        self.assertEqual(('a', 'b', 'c'), walk.track_ids)

    def test_unknown_artists_are_unconstrained(self):
        walk = walk_playlist('a', tracks('a', 'b'), related(('a', 'b', 0.9)), TrackCountGoal(2))

        self.assertEqual(('a', 'b'), walk.track_ids)

    def test_duration_goal_stops_once_the_target_is_reached(self):
        library = tracks('a', 'b', 'c', 'd', durations={'a': 200.0, 'b': 200.0, 'c': 250.0, 'd': 300.0})
        chain = related(('a', 'b', 0.9), ('b', 'c', 0.9), ('c', 'd', 0.9))

        walk = walk_playlist('a', library, chain, DurationGoal(seconds=600.0, max_tracks=1000))

        self.assertEqual(('a', 'b', 'c'), walk.track_ids, '650 s reaches 600 s; d is not needed')
        self.assertTrue(walk.complete)

    def test_duration_goal_skips_tracks_without_a_duration(self):
        library = tracks('a', 'b', 'c', durations={'a': 300.0, 'b': None, 'c': 300.0})

        walk = walk_playlist('a', library, related(('a', 'b', 0.9), ('a', 'c', 0.5)),
                             DurationGoal(seconds=600.0, max_tracks=1000))

        self.assertEqual(('a', 'c'), walk.track_ids)

    def test_duration_goal_is_incomplete_when_the_track_cap_comes_first(self):
        library = tracks('a', 'b', 'c', durations={'a': 60.0, 'b': 60.0, 'c': 60.0})

        walk = walk_playlist('a', library, related(('a', 'b', 0.9), ('b', 'c', 0.9)),
                             DurationGoal(seconds=600.0, max_tracks=2))

        self.assertEqual(('a', 'b'), walk.track_ids)
        self.assertFalse(walk.complete)

    def test_bounded_search_returns_the_longest_walk_found(self):
        # A complete binary tree with no path of length 30: the search cannot
        # succeed, and must stop at its expansion limit rather than explore 2^n.
        ids = [f'n{i:05d}' for i in range(2 ** 12 - 1)]
        edges = [(ids[i], ids[c], 0.5) for i in range(len(ids)) for c in (2 * i + 1, 2 * i + 2) if c < len(ids)]

        walk = walk_playlist(ids[0], tracks(*ids), related(*edges), TrackCountGoal(30), expansion_limit=500)

        self.assertFalse(walk.complete)
        self.assertEqual(12, len(walk.track_ids), 'root-to-leaf, the longest walk in the tree')

    def test_same_inputs_give_the_same_walk(self):
        ids = [f't{i}' for i in range(20)]
        edges = [(ids[i], ids[j], 0.5) for i in range(20) for j in range(i + 1, 20) if (i * j) % 3]
        walks = {walk_playlist('t0', tracks(*ids), related(*edges), TrackCountGoal(10)).track_ids for _ in range(5)}

        self.assertEqual(1, len(walks))


if __name__ == '__main__':
    unittest.main()
