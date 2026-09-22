import unittest
from dataclasses import replace

from music_analyzer.application.dto.analysis import AnalysisReport, StageResult
from music_analyzer.application.dto.explorer import ExplorerStoredTrack
from music_analyzer.application.use_cases.explorer import BuildMoodAxisGraph, FilterMoodAxisGraph
from music_analyzer.domain.analysis import ScoreSummary


def summary(labels, values, provisional=True):
    return ScoreSummary(tuple(labels), tuple(values), tuple(values), tuple(values), 1.0, provisional, '')


def track(suffix, *, bpm=120.0, energy=(0.25, 0.75), mood=(('relaxing', 'heavy'), (0.8, 0.2)), genres=(('rock', 'jazz'), (0.9, 0.1)), overrides=()):
    stages = []
    if bpm is not None:
        stages.append(StageResult('bpm', (('engine', 'test-bpm'),), '', (('bpm', bpm),)))
    if energy is not None:
        stages.append(StageResult('energy', (('emomusic-msd-musicnn-2', 'synthetic-sha256'), ('scale', 'native_valence_arousal_regression')), '', summary=summary(('valence', 'arousal'), energy)))
    if mood is not None:
        stages.append(StageResult('mood', (('mtg_jamendo_moodtheme-discogs-effnet-1', 'synthetic-sha256'), ('scale', 'sigmoid_mean_score_0_1')), '', summary=summary(mood[0], mood[1])))
    if genres is not None:
        stages.append(StageResult('genres', (('genre_discogs400-discogs-effnet-1', 'synthetic-sha256'), ('threshold', '0.5')), '', summary=summary(genres[0], genres[1])))
    return ExplorerStoredTrack('sha256:' + suffix * 64, suffix * 64, 10, suffix + '.flac', 1, AnalysisReport('run-' + suffix, 'completed', tuple(stages)), overrides)


class FakeRepo:
    def __init__(self, records): self.records = tuple(records)
    def candidate_snapshot(self): return {'application_id': 1, 'schema_version': 4, 'read_policy': 'bounded_read_transaction'}, self.records


class MoodAxisGraphTests(unittest.TestCase):
    def test_axis_mapping_retains_raw_values_normalized_display_metadata_and_selected_mood(self):
        graph = BuildMoodAxisGraph(FakeRepo([track('a')])).execute('relaxing')
        node = graph.positioned[0]
        self.assertEqual((node.x.raw, node.y.raw, node.z.raw), (0.25, 0.75, 0.8))
        self.assertEqual((node.x.normalized, node.y.normalized, node.z.normalized), (0.25, 0.75, 0.6))
        self.assertEqual((node.x.label, node.y.label, node.z.label), ('valence', 'arousal', 'relaxing'))
        self.assertEqual(node.z.provenance, (('mtg_jamendo_moodtheme-discogs-effnet-1', 'synthetic-sha256'), ('scale', 'sigmoid_mean_score_0_1')))
        self.assertEqual(graph.metadata['coordinate_policy'], 'fixed-mood-axis-v1')
        self.assertIn('relaxing', graph.available_moods)

    def test_missing_required_axis_data_is_unpositioned_without_zero_fallback(self):
        graph = BuildMoodAxisGraph(FakeRepo([track('a', energy=None), track('b', mood=None)])).execute('relaxing')
        self.assertEqual(graph.positioned, ())
        reasons = {item.track_id: item.reasons for item in graph.unpositioned}
        self.assertTrue(any('energy: missing valence' in r for r in reasons['sha256:' + 'a' * 64]))
        self.assertTrue(any('mood: missing selected label relaxing' in r for r in reasons['sha256:' + 'b' * 64]))

    def test_incompatible_axis_model_or_out_of_scale_value_is_unpositioned_not_clipped(self):
        base = track('a')
        bad_stages = list(base.run.stages)
        bad_stages[1] = replace(bad_stages[1], provenance=(('other-energy-model', 'synthetic-sha256'),))
        bad_model = replace(base, run=replace(base.run, stages=tuple(bad_stages)))
        out_of_scale = track('b', mood=(('relaxing',), (1.5,)))
        graph = BuildMoodAxisGraph(FakeRepo([bad_model, out_of_scale])).execute('relaxing')
        self.assertEqual(graph.positioned, ())
        reasons = {item.track_id: item.reasons for item in graph.unpositioned}
        self.assertIn('energy: incompatible model/scale for fixed valence/arousal axis', reasons['sha256:' + 'a' * 64])
        self.assertIn('mood: selected label relaxing outside supported [0,1] score scale', reasons['sha256:' + 'b' * 64])

    def test_mood_alias_validation_and_unsupported_label_lists_available(self):
        graph = BuildMoodAxisGraph(FakeRepo([track('a', mood=(('relaxing', 'heavy'), (0.1, 0.9)))])).execute('Relaxing')
        self.assertEqual(graph.selected_mood, 'relaxing')
        with self.assertRaisesRegex(ValueError, 'Unsupported mood label angry; available: heavy, relaxing'):
            BuildMoodAxisGraph(FakeRepo([track('a', mood=(('relaxing', 'heavy'), (0.1, 0.9)))])).execute('angry')

    def test_no_supported_mood_returns_all_unpositioned_graph_without_aborting_default_view(self):
        graph = BuildMoodAxisGraph(FakeRepo([track('a', mood=None), track('b', mood=None)])).execute()
        self.assertEqual(graph.selected_mood, '')
        self.assertEqual(graph.available_moods, ())
        self.assertEqual(graph.positioned, ())
        self.assertEqual({item.track_id for item in graph.unpositioned}, {'sha256:' + 'a' * 64, 'sha256:' + 'b' * 64})
        self.assertTrue(all(any('mood: no supported labels available' in reason for reason in item.reasons) for item in graph.unpositioned))
        with self.assertRaisesRegex(ValueError, 'Unsupported mood label angry; available: none'):
            BuildMoodAxisGraph(FakeRepo([track('a', mood=None)])).execute('angry')

    def test_filters_bpm_bounds_genre_any_clear_and_coordinates_stable(self):
        graph = BuildMoodAxisGraph(FakeRepo([track('a', bpm=100, genres=(('rock','jazz'), (0.6,0.1))), track('b', bpm=130, genres=(('rock','jazz'), (0.1,0.7)))])).execute('relaxing')
        filtered = FilterMoodAxisGraph().execute(graph, bpm_min=90, bpm_max=110, genres=('jazz',))
        self.assertEqual([n.track_id for n in filtered.positioned], [])
        filtered = FilterMoodAxisGraph().execute(graph, bpm_min=90, bpm_max=110, genres=('rock',))
        self.assertEqual([n.track_id for n in filtered.positioned], ['sha256:' + 'a' * 64])
        cleared = FilterMoodAxisGraph().execute(graph)
        self.assertEqual(tuple((n.track_id, n.x.normalized, n.y.normalized, n.z.normalized) for n in cleared.positioned), tuple((n.track_id, n.x.normalized, n.y.normalized, n.z.normalized) for n in graph.positioned))

    def test_selected_mood_changes_only_z_and_edges_include_axis_independent_explanation(self):
        records = [track('a', mood=(('relaxing','heavy'), (0.2,0.9))), track('b', energy=(0.25,0.75), mood=(('relaxing','heavy'), (0.7,0.1)))]
        relaxing = BuildMoodAxisGraph(FakeRepo(records)).execute('relaxing')
        heavy = BuildMoodAxisGraph(FakeRepo(records)).execute('heavy')
        self.assertEqual([(n.x.normalized, n.y.normalized) for n in relaxing.positioned], [(n.x.normalized, n.y.normalized) for n in heavy.positioned])
        self.assertNotEqual([n.z.normalized for n in relaxing.positioned], [n.z.normalized for n in heavy.positioned])
        self.assertTrue(relaxing.edges)
        edge = relaxing.edges[0]
        self.assertIn('axis-independent', edge.explanation)
        self.assertEqual(edge.provenance['policy'], 'symmetric-feature-distance-v1')
        self.assertLessEqual(len(relaxing.edges), 20)


if __name__ == '__main__':
    unittest.main()
