import json
import math
import unittest

from music_explorer.application.dto.explorer import AxisValue, MoodAxisEdge, MoodAxisGraph, MoodAxisNode, UnpositionedTrack


class IndexedMoodAxisGraphHttpMapperRedTests(unittest.TestCase):
    def _indexed_mapper(self):
        from music_explorer.interface_adapters import mood_axis_graph_http

        mapper = getattr(mood_axis_graph_http, 'to_indexed_mood_axis_graph_http', None)
        self.assertTrue(
            callable(mapper),
            'Issue #44 v3 red test expects an indexed/dictionary HTTP mapper named '
            'to_indexed_mood_axis_graph_http at the interface-adapter boundary.',
        )
        return mapper

    def _graph(self):
        return MoodAxisGraph(
            metadata={
                'graph_status': {'state': 'ready', 'source_revision': 'rev-v3', 'policy': 'sparse_k10'},
                'source_fingerprint': 'fp-v3',
                'track_count': 3,
            },
            selected_mood='relaxing',
            available_moods=('relaxing', 'heavy'),
            positioned=(
                MoodAxisNode(
                    track_id='sha256:' + 'a' * 64,
                    display_label='Alpha.flac',
                    x=AxisValue('valence', 0.7, 0.7, 'native-emomusic-valence-regression', (('model', 'v1'),)),
                    y=AxisValue('arousal', 0.2, 0.2, 'native-emomusic-arousal-regression', (('model', 'v1'),)),
                    z=AxisValue('BPM', 120.0, 6.0, 'fixed-BPM/20-display-units'),
                    bpm=120.0,
                    genres=(('rock', 0.8), ('jazz', 0.2)),
                    reasons=('genre threshold 0.5',),
                    genre_threshold=0.5,
                    mood_score=AxisValue('relaxing', 0.9, 0.9, 'sigmoid_mean_score_0_1', (('mood-model', 'sha'),)),
                ),
                MoodAxisNode(
                    track_id='sha256:' + 'b' * 64,
                    display_label='Beta.flac',
                    x=AxisValue('valence', 0.4, 0.4, 'native-emomusic-valence-regression', (('model', 'v1'),)),
                    y=AxisValue('arousal', 0.6, 0.6, 'native-emomusic-arousal-regression', (('model', 'v1'),)),
                    z=AxisValue('BPM', 100.0, 5.0, 'fixed-BPM/20-display-units'),
                    bpm=100.0,
                    genres=(('rock', 0.7),),
                    reasons=('genre threshold 0.5',),
                    genre_threshold=0.5,
                    mood_score=AxisValue('relaxing', 0.8, 0.8, 'sigmoid_mean_score_0_1', (('mood-model', 'sha'),)),
                ),
            ),
            unpositioned=(UnpositionedTrack('sha256:' + 'c' * 64, 'Missing.flac', ('genre threshold 0.5',)),),
            edges=(
                MoodAxisEdge(
                    a='sha256:' + 'a' * 64,
                    b='sha256:' + 'b' * 64,
                    score=0.77,
                    explanation='axis-independent relatedness',
                    provenance={'policy': 'sparse_k10', 'source': 'persisted-positioned-edges'},
                    supported_group_count=3,
                ),
            ),
        )

    def test_indexed_mapper_is_versioned_dictionary_contract_and_reconstructs_losslessly(self):
        to_indexed_mood_axis_graph_http = self._indexed_mapper()

        indexed = to_indexed_mood_axis_graph_http(self._graph())
        self.assertEqual(indexed['dto_version'], 'mood-axis-graph-indexed-v1')
        self.assertEqual(indexed['metadata']['graph_status']['source_revision'], 'rev-v3')
        self.assertEqual(indexed['axis'][0], {'key': 'x', 'label': 'valence', 'scale': 'native-emomusic-valence-regression'})
        self.assertEqual(indexed['genre_labels'], ['rock', 'jazz'])
        self.assertEqual(indexed['reason_text'], ['genre threshold 0.5'])
        self.assertEqual(indexed['explanation_table'], ['axis-independent relatedness'])
        self.assertEqual(indexed['provenance_table'], [{'policy': 'sparse_k10', 'source': 'persisted-positioned-edges'}])
        self.assertEqual(indexed['link_defaults'], {'explanation': 0, 'provenance': 0})
        self.assertNotIn('positioned', indexed)
        self.assertNotIn('edges', indexed)
        self.assertIsInstance(indexed['nodes'][0], list)
        self.assertEqual(indexed['nodes'][0][0], 'sha256:' + 'a' * 64)
        self.assertEqual(indexed['nodes'][0][10], [[0, 0.8], [1, 0.2]])
        self.assertEqual(indexed['nodes'][0][11], [0])
        self.assertEqual(indexed['unpositioned'][0], ['sha256:' + 'c' * 64, 'Missing.flac', [0]])
        self.assertEqual(indexed['links'][0], [0, 1, 0.77, 3])
        reconstructed_edge = indexed['links'][0]
        self.assertEqual(indexed['nodes'][reconstructed_edge[0]][0], 'sha256:' + 'a' * 64)
        self.assertEqual(indexed['nodes'][reconstructed_edge[1]][0], 'sha256:' + 'b' * 64)
        self.assertEqual(indexed['explanation_table'][indexed['link_defaults']['explanation']], 'axis-independent relatedness')
        self.assertEqual(indexed['provenance_table'][indexed['link_defaults']['provenance']]['policy'], 'sparse_k10')
        json.dumps(indexed, sort_keys=True, ensure_ascii=False, allow_nan=False)

    def test_indexed_mapper_rejects_nonfinite_numbers_before_json_serialization(self):
        to_indexed_mood_axis_graph_http = self._indexed_mapper()

        graph = self._graph()
        bad_node = MoodAxisNode(
            track_id='sha256:' + 'd' * 64,
            display_label='Bad.flac',
            x=AxisValue('valence', math.nan, 0.5, 'native-emomusic-valence-regression'),
            y=AxisValue('arousal', 0.2, 0.2, 'native-emomusic-arousal-regression'),
            z=AxisValue('BPM', 120.0, 6.0, 'fixed-BPM/20-display-units'),
            bpm=120.0,
            genres=(),
        )
        with self.assertRaises(ValueError):
            to_indexed_mood_axis_graph_http(MoodAxisGraph(graph.metadata, graph.selected_mood, graph.available_moods, (bad_node,), (), ()))

    def test_indexed_mapper_rejects_edges_that_do_not_reference_positioned_nodes(self):
        to_indexed_mood_axis_graph_http = self._indexed_mapper()

        graph = self._graph()
        bad_edge = MoodAxisEdge('sha256:' + 'a' * 64, 'sha256:' + 'z' * 64, 0.1, 'axis-independent relatedness', {'policy': 'sparse_k10'}, 1)
        with self.assertRaises(ValueError):
            to_indexed_mood_axis_graph_http(MoodAxisGraph(graph.metadata, graph.selected_mood, graph.available_moods, graph.positioned, graph.unpositioned, (bad_edge,)))


if __name__ == '__main__':
    unittest.main()
