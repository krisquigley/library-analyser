import math
import unittest

from music_analyzer.domain.candidate_selection import CandidateFeatures, FeatureEvidence
from music_analyzer.domain.projection import (
    NEIGHBOUR_POLICY_VERSION,
    PROJECTION_POLICY_VERSION,
    ProjectionParameters,
    fit_projection_transform,
    project_tracks,
    symmetric_feature_distance,
)


def features(track_id, *, bpm=None, arousal=None, genres=(), genre_model='g-v1', mood=(), mood_model='mood-v1', manual_bpm=None):
    fields = {}
    if bpm is not None or manual_bpm is not None:
        fields['bpm'] = FeatureEvidence(
            values=((('bpm', bpm),) if bpm is not None else ()),
            manual_text=manual_bpm,
            effective_source='manual_text' if manual_bpm is not None else 'automatic',
        )
    if arousal is not None:
        fields['energy'] = FeatureEvidence(summary_values=(('arousal', arousal),), effective_source='automatic')
    if genres:
        fields['genres'] = FeatureEvidence(
            summary_values=tuple(genres),
            provenance=(('model', genre_model),),
            effective_source='automatic',
        )
    if mood:
        fields['mood'] = FeatureEvidence(
            summary_values=tuple(mood),
            provenance=(('model', mood_model),),
            effective_source='automatic',
        )
    return CandidateFeatures(track_id, fields)


def _edge_ids(edges):
    return {tuple(sorted((edge.a, edge.b))) for edge in edges}


class ProjectionContractTests(unittest.TestCase):
    def test_version_strings_are_frozen(self):
        self.assertEqual(PROJECTION_POLICY_VERSION, 'anchor-distance-projection-v1')
        self.assertEqual(NEIGHBOUR_POLICY_VERSION, 'endpoint-local-exact-top-k-neighbours-v2')

    def test_fit_persists_deterministic_anchors_and_transform(self):
        tracks = (
            features('b', bpm=130, arousal=0.5),
            features('a', bpm=100, arousal=-0.2),
            features('c', bpm=160, arousal=0.9),
        )
        transform = fit_projection_transform(tracks, ProjectionParameters(k=2))

        self.assertEqual(transform.policy_version, 'anchor-distance-projection-v1')
        self.assertEqual(transform.anchors['tempo'].low_track_id, 'a')
        self.assertEqual(transform.anchors['tempo'].high_track_id, 'c')
        self.assertEqual(transform.anchors['energy'].low_track_id, 'a')
        self.assertEqual(transform.anchors['energy'].high_track_id, 'c')
        self.assertTrue(math.isfinite(transform.center_x))
        self.assertGreater(transform.range_x, 0.0)

    def test_identical_complete_tracks_get_honest_degenerate_positions(self):
        tracks = (
            features('a', bpm=120, arousal=0.2, genres=(('rock', 1.0),), mood=(('calm', 1.0),)),
            features('b', bpm=120, arousal=0.2, genres=(('rock', 1.0),), mood=(('calm', 1.0),)),
        )
        projection = project_tracks(tracks, fit_projection_transform(tracks, ProjectionParameters(k=1)))

        self.assertEqual(projection.transform.anchors, {})
        by_id = {point.track_id: point for point in projection.points}
        for track_id in ('a', 'b'):
            self.assertEqual(by_id[track_id].layout_state, 'degenerate')
            self.assertEqual((by_id[track_id].x, by_id[track_id].y), (0.0, 0.0))
            self.assertEqual(by_id[track_id].missing_groups, ())
            self.assertEqual(by_id[track_id].missing_reasons, ())
        self.assertEqual(_edge_ids(projection.edges), {('a', 'b')})

    def test_one_complete_track_gets_degenerate_position_without_fabricated_similarity(self):
        track = features('solo', bpm=120, arousal=0.2, genres=(('rock', 1.0),), mood=(('calm', 1.0),))
        projection = project_tracks((track,), fit_projection_transform((track,), ProjectionParameters(k=1)))
        point = projection.points[0]

        self.assertEqual(point.layout_state, 'degenerate')
        self.assertEqual((point.x, point.y), (0.0, 0.0))
        self.assertEqual(point.missing_groups, ())
        self.assertEqual(projection.edges, ())

    def test_genuinely_missing_track_stays_isolated_when_transform_has_no_anchors(self):
        projection = project_tracks((features('missing'),), fit_projection_transform((features('missing'),), ProjectionParameters(k=1)))
        point = projection.points[0]

        self.assertEqual(point.layout_state, 'missing')
        self.assertIsNone(point.x)
        self.assertIsNone(point.y)
        self.assertIn('tempo', point.missing_groups)
        self.assertIn('tempo: missing usable evidence', point.missing_reasons)
        self.assertEqual(projection.edges, ())

    def test_mixed_single_complete_and_missing_tracks_distinguish_degenerate_from_absent(self):
        tracks = (
            features('complete', bpm=120, arousal=0.2, genres=(('rock', 1.0),), mood=(('calm', 1.0),)),
            features('missing'),
        )
        projection = project_tracks(tracks, fit_projection_transform(tracks, ProjectionParameters(k=1)))
        by_id = {point.track_id: point for point in projection.points}

        self.assertEqual(by_id['complete'].layout_state, 'degenerate')
        self.assertEqual((by_id['complete'].x, by_id['complete'].y), (0.0, 0.0))
        self.assertEqual(by_id['complete'].missing_groups, ())
        self.assertEqual(by_id['missing'].layout_state, 'missing')
        self.assertIsNone(by_id['missing'].x)
        self.assertIn('genre', by_id['missing'].missing_groups)
        self.assertEqual(projection.edges, ())

    def test_missing_manual_or_incompatible_groups_do_not_fabricate_positions(self):
        fitted = (
            features('a', bpm=100, arousal=-1.0, genres=(('house', 1.0), ('techno', 0.0))),
            features('b', bpm=150, arousal=1.0, genres=(('house', 0.0), ('techno', 1.0))),
        )
        transform = fit_projection_transform(fitted, ProjectionParameters(k=1))
        projected = project_tracks((
            features('manual', bpm=120, manual_bpm='fast'),
            features('other-model', genres=(('house', 0.2), ('techno', 0.8)), genre_model='g-v2'),
        ), transform)

        by_id = {point.track_id: point for point in projected.points}
        self.assertEqual(by_id['manual'].layout_state, 'missing')
        self.assertIsNone(by_id['manual'].x)
        self.assertIsNone(by_id['manual'].y)
        self.assertIn('tempo', by_id['manual'].missing_groups)
        self.assertEqual(by_id['other-model'].layout_state, 'missing')
        self.assertIn('genre: incompatible label/model alignment', by_id['other-model'].missing_reasons)
        self.assertEqual(projected.edges, ())

    def test_symmetric_distance_skips_missing_and_incompatible_evidence(self):
        a = features('a', bpm=120, arousal=0.0, genres=(('house', 1.0), ('techno', 0.0)))
        b = features('b', bpm=240, arousal=1.0, genres=(('house', 0.0), ('techno', 1.0)))
        c = features('c', genres=(('house', 0.5), ('techno', 0.5)), genre_model='other')

        ab = symmetric_feature_distance(a, b)
        ba = symmetric_feature_distance(b, a)
        self.assertAlmostEqual(ab.distance, ba.distance)
        self.assertGreater(ab.supported_group_count, 1)
        self.assertIn('tempo', ab.group_distances)
        self.assertEqual(symmetric_feature_distance(a, c).group_distances, {})

    def test_neighbour_selection_uses_exact_feature_distances_beyond_scalar_window(self):
        # a and z are closest by genre vector, but z is more than the old
        # scalar-order window away from a because tempo orders m00..m24 first.
        tracks = [features('a', bpm=100, genres=(('close', 1.0), ('far', 0.0)))]
        for i in range(25):
            tracks.append(features(f'm{i:02d}', bpm=101 + i, genres=(('close', 0.0), ('far', 1.0))))
        tracks.append(features('z', bpm=1000, genres=(('close', 1.0), ('far', 0.0))))

        projection = project_tracks(tuple(tracks), fit_projection_transform(tuple(tracks), ProjectionParameters(k=1)))

        edges = {(edge.a, edge.b): edge.distance for edge in projection.edges}
        self.assertIn(('a', 'z'), edges)
        self.assertLess(edges[('a', 'z')], symmetric_feature_distance(tracks[0], tracks[1]).distance)
        self.assertNotIn(('a', 'm00'), edges)



    def test_endpoint_local_top_k_oracle_with_ties_missing_and_model_partitions(self):
        tracks = (
            features('a', arousal=0.0, mood=(('calm', 1.0),), genres=(('jazz', 1.0),), genre_model='m1'),
            features('b', arousal=0.0, mood=(('calm', 1.0),), genres=(('jazz', 1.0),), genre_model='m1'),
            features('c', arousal=0.3, mood=(('calm', 1.0),), genres=(('jazz', 1.0),), genre_model='m1'),
            features('d', arousal=0.8, mood=(('calm', 1.0),), genres=(('jazz', 1.0),), genre_model='m1'),
            features('e', arousal=0.05, mood=(('calm', 1.0),), genres=(('jazz', 1.0),), genre_model='m2'),
            features('f', bpm=None, arousal=None, mood=(), genres=()),
        )
        edges = _edge_ids(project_tracks(tuple(reversed(tracks)), fit_projection_transform(tracks, ProjectionParameters(k=2))).edges)

        self.assertEqual(edges, {('a', 'b'), ('a', 'e'), ('b', 'e'), ('c', 'd')})

    def test_endpoint_local_policy_intentionally_differs_from_global_greedy_fill(self):
        import music_analyzer.domain.projection as projection

        tracks = tuple(features(track_id, bpm=100, arousal=0.1) for track_id in ('u', 'v', 'x', 'y'))
        selector = projection._SparseNeighbourSelector(tracks, k=1)
        for a, b, distance in (
            ('x', 'y', 0.1),
            ('u', 'x', 0.2),
            ('v', 'y', 0.3),
            ('u', 'v', 0.4),
            ('u', 'y', 0.9),
            ('v', 'x', 1.0),
        ):
            selector.consider(a, b, distance, 1)

        edges = _edge_ids(selector.edges())

        self.assertEqual(edges, {('x', 'y')})
        self.assertNotIn(('u', 'v'), edges)

    def test_endpoint_local_selection_is_symmetric_and_permutation_deterministic(self):
        tracks = tuple(features(chr(ord('a') + i), bpm=100 + (i % 3), arousal=(i % 5) / 10) for i in range(9))
        transform = fit_projection_transform(tracks, ProjectionParameters(k=3))
        forward = _edge_ids(project_tracks(tracks, transform).edges)
        reverse = _edge_ids(project_tracks(tuple(reversed(tracks)), transform).edges)
        shuffled = _edge_ids(project_tracks((tracks[3], tracks[1], tracks[8], tracks[0], tracks[5], tracks[2], tracks[7], tracks[4], tracks[6]), transform).edges)

        self.assertEqual(forward, reverse)
        self.assertEqual(forward, shuffled)

    def test_exact_neighbour_selection_does_not_retain_all_finite_pairs(self):
        import music_analyzer.domain.projection as projection

        tracks = tuple(features(str(i), bpm=100 + i, arousal=i / 10) for i in range(12))
        original = projection._SparseNeighbourSelector

        class FailingSelector(original):
            def consider(self, *args, **kwargs):
                super().consider(*args, **kwargs)
                retained = sum(len(values) for values in self._candidates.values())
                if retained > len(tracks) * self._k * 2:
                    raise AssertionError('retained unbounded pair proposals')

        try:
            projection._SparseNeighbourSelector = FailingSelector
            result = project_tracks(tracks, fit_projection_transform(tracks, ProjectionParameters(k=2)))
        finally:
            projection._SparseNeighbourSelector = original

        self.assertLessEqual(len(result.edges), len(tracks) * 2 // 2)

    def test_undirected_neighbour_degree_is_bounded_by_k_without_dense_matrix(self):
        tracks = tuple(features(str(i), bpm=100 + i, arousal=i / 10) for i in range(8))
        projection = project_tracks(tracks, fit_projection_transform(tracks, ProjectionParameters(k=2)))

        degree = {track.track_id: 0 for track in tracks}
        for edge in projection.edges:
            degree[edge.a] += 1
            degree[edge.b] += 1
            self.assertGreaterEqual(edge.supported_group_count, 1)
        self.assertLess(len(projection.edges), len(tracks) * len(tracks))
        self.assertLessEqual(max(degree.values()), 2)


if __name__ == '__main__':
    unittest.main()
