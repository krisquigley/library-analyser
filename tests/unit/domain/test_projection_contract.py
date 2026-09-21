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


def features(track_id, *, bpm=None, arousal=None, genres=(), genre_model='g-v1', manual_bpm=None):
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
    return CandidateFeatures(track_id, fields)


class ProjectionContractTests(unittest.TestCase):
    def test_version_strings_are_frozen(self):
        self.assertEqual(PROJECTION_POLICY_VERSION, 'anchor-distance-projection-v1')
        self.assertEqual(NEIGHBOUR_POLICY_VERSION, 'bounded-symmetric-neighbours-v1')

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
