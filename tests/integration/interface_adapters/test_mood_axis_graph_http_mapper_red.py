import importlib
import importlib.util
import json
import unittest

from music_explorer.application.dto.explorer import AxisValue, MoodAxisEdge, MoodAxisGraph, MoodAxisNode, UnpositionedTrack


class MoodAxisGraphHttpMapperRedTests(unittest.TestCase):
    def test_compact_http_mapper_is_an_outer_boundary_adapter_with_browser_semantics(self):
        spec = importlib.util.find_spec('music_explorer.interface_adapters.mood_axis_graph_http')
        self.assertIsNotNone(spec, 'expected compact graph HTTP mapper at the interface-adapter boundary')
        mapper = importlib.import_module('music_explorer.interface_adapters.mood_axis_graph_http')
        graph = MoodAxisGraph(
            metadata={
                'graph_status': {'state': 'ready', 'source_revision': 'rev-1'},
                'source_fingerprint': 'fp-1',
                'track_count': 3,
            },
            selected_mood='relaxing',
            available_moods=('relaxing', 'heavy'),
            positioned=(
                MoodAxisNode(
                    track_id='track-a',
                    display_label='Alpha',
                    x=AxisValue('valence', 0.7, 0.7, 'native', (('energy-model', 'sha'),)),
                    y=AxisValue('arousal', 0.2, 0.2, 'native', (('energy-model', 'sha'),)),
                    z=AxisValue('BPM', 120.0, 6.0, 'fixed-BPM/20-display-units'),
                    bpm=120.0,
                    genres=(('rock', 0.8), ('jazz', 0.2)),
                    reasons=('genre threshold 0.5',),
                    genre_threshold=0.5,
                    mood_score=AxisValue('relaxing', 0.9, 0.9, 'sigmoid_mean_score_0_1', (('mood-model', 'sha'),)),
                ),
            ),
            unpositioned=(UnpositionedTrack('track-missing', 'Missing', ('mood: no supported labels available',)),),
            edges=(
                MoodAxisEdge(
                    a='track-a',
                    b='track-b',
                    score=0.77,
                    explanation='axis-independent relatedness',
                    provenance={'policy': 'sparse_k10'},
                    supported_group_count=3,
                ),
            ),
        )

        compact = mapper.to_compact_mood_axis_graph_http(graph)
        self.assertEqual(compact['dto_version'], 'mood-axis-graph-compact-v1')
        self.assertEqual(compact['metadata']['graph_status']['source_revision'], 'rev-1')
        self.assertEqual(compact['selected_mood'], 'relaxing')
        self.assertEqual(compact['available_moods'], ['relaxing', 'heavy'])
        self.assertNotIn('positioned', compact)
        self.assertNotIn('edges', compact)
        self.assertEqual(compact['nodes'][0]['id'], 'track-a')
        self.assertEqual(compact['nodes'][0]['label'], 'Alpha')
        self.assertEqual(compact['nodes'][0]['axis']['x']['raw'], 0.7)
        self.assertEqual(compact['nodes'][0]['axis']['x']['normalized'], 0.7)
        self.assertEqual(compact['nodes'][0]['axis']['z']['raw'], 120.0)
        self.assertEqual(compact['nodes'][0]['bpm'], 120.0)
        self.assertEqual(compact['nodes'][0]['genres'], [['rock', 0.8], ['jazz', 0.2]])
        self.assertEqual(compact['nodes'][0]['genre_threshold'], 0.5)
        self.assertEqual(compact['nodes'][0]['mood_score']['label'], 'relaxing')
        self.assertEqual(compact['nodes'][0]['reasons'], ['genre threshold 0.5'])
        self.assertEqual(compact['unpositioned'][0]['id'], 'track-missing')
        self.assertEqual(compact['unpositioned'][0]['label'], 'Missing')
        self.assertEqual(compact['unpositioned'][0]['reasons'], ['mood: no supported labels available'])
        self.assertEqual(compact['links'][0]['source'], 'track-a')
        self.assertEqual(compact['links'][0]['target'], 'track-b')
        self.assertEqual(compact['links'][0]['score'], 0.77)
        self.assertEqual(compact['links'][0]['explanation'], 'axis-independent relatedness')
        self.assertEqual(compact['links'][0]['provenance'], {'policy': 'sparse_k10'})
        self.assertEqual(compact['links'][0]['supported_group_count'], 3)
        json.dumps(compact, sort_keys=True, ensure_ascii=False, allow_nan=False)


if __name__ == '__main__':
    unittest.main()
