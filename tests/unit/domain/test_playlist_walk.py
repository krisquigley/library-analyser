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

    def test_a_transition_ranking_reorders_the_choices(self):
        # #122: the walk follows the best-ranked transition, not just the strongest relation.
        def prefer_c(walk, to_track, relation_score, position):
            return relation_score + (0.5 if to_track.track_id == 'c' else 0.0)

        walk = walk_playlist('a', tracks('a', 'b', 'c'), related(('a', 'b', 0.9), ('a', 'c', 0.6)),
                             TrackCountGoal(2), rank_transition=prefer_c)

        self.assertEqual(('a', 'c'), walk.track_ids)

    def test_the_ranking_sees_the_tracks_on_both_sides_of_the_transition(self):
        seen = []

        def record(walk, to_track, relation_score, position):
            seen.append((walk[-1].track_id, to_track.track_id, relation_score))
            return relation_score

        walk_playlist('a', tracks('a', 'b'), related(('a', 'b', 0.9)), TrackCountGoal(2), rank_transition=record)

        self.assertIn(('a', 'b', 0.9), seen)

    def test_the_ranking_sees_the_whole_walk_so_far(self):
        # #135: a chained energy arc anchors on the track that ended the previous arc.
        walks = {}

        def record(walk, to_track, relation_score, position):
            walks.setdefault(to_track.track_id, tuple(track.track_id for track in walk))
            return relation_score

        walk_playlist('a', tracks('a', 'b', 'c'), related(('a', 'b', 0.9), ('b', 'c', 0.9)),
                      TrackCountGoal(3), rank_transition=record)

        self.assertEqual(('a', 'b'), walks['c'])

    def test_the_ranking_knows_where_in_the_playlist_the_next_track_falls(self):
        # #123: an energy arc targets a level per position, 0 at the start and 1 at the end.
        positions = {}

        def record(walk, to_track, relation_score, position):
            if to_track.track_id != 'a':
                positions.setdefault(to_track.track_id, position)
            return relation_score

        walk_playlist('a', tracks('a', 'b', 'c', 'd', 'e'),
                      related(('a', 'b', 0.9), ('b', 'c', 0.9), ('c', 'd', 0.9), ('d', 'e', 0.9)),
                      TrackCountGoal(5), rank_transition=record)

        self.assertEqual({'b': 0.25, 'c': 0.5, 'd': 0.75, 'e': 1.0}, positions)

    def test_a_position_dependent_ranking_can_change_the_choice_later_in_the_playlist(self):
        def late_prefers_z(walk, to_track, relation_score, position):
            return relation_score + (1.0 if position == 1.0 and to_track.track_id == 'z' else 0.0)

        walk = walk_playlist('a', tracks('a', 'b', 'y', 'z'),
                             related(('a', 'b', 0.9), ('a', 'z', 0.1), ('b', 'y', 0.9), ('b', 'z', 0.5)),
                             TrackCountGoal(3), rank_transition=late_prefers_z)

        self.assertEqual(('a', 'b', 'z'), walk.track_ids)


class GoalPositionTests(unittest.TestCase):
    def test_track_count_position_runs_from_the_start_to_the_last_track(self):
        goal = TrackCountGoal(3)
        library = tracks('a', 'b', 'c')

        self.assertEqual([0.5, 1.0], [goal.position([library['a']]), goal.position([library['a'], library['b']])])

    def test_a_single_track_playlist_is_already_at_the_end(self):
        self.assertEqual(1.0, TrackCountGoal(1).position([]))

    def test_duration_position_is_the_elapsed_share_of_the_target(self):
        library = tracks('a', 'b', durations={'a': 300.0, 'b': 900.0})
        goal = DurationGoal(seconds=600.0, max_tracks=10)

        self.assertEqual([0.5, 1.0], [goal.position([library['a']]), goal.position([library['a'], library['b']])])

    def test_same_inputs_give_the_same_walk(self):
        ids = [f't{i}' for i in range(20)]
        edges = [(ids[i], ids[j], 0.5) for i in range(20) for j in range(i + 1, 20) if (i * j) % 3]
        walks = {walk_playlist('t0', tracks(*ids), related(*edges), TrackCountGoal(10)).track_ids for _ in range(5)}

        self.assertEqual(1, len(walks))


if __name__ == '__main__':
    unittest.main()
