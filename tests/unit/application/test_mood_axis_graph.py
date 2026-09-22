import unittest

from music_analyzer.application.dto.analysis import AnalysisReport, StageResult
from music_analyzer.application.dto.explorer import ExplorerStoredTrack
from music_analyzer.application.use_cases.explorer import BuildMoodAxisGraph, FilterMoodAxisGraph
from music_analyzer.domain.analysis import ScoreSummary


def summary(labels, values, provisional=True):
    return ScoreSummary(tuple(labels), tuple(values), tuple(values), tuple(values), 1.0, provisional, '')


def track(suffix, *, bpm=120.0, energy=(0.25, 0.75), mood=(('happy', 'relaxed'), (0.8, 0.2)), genres=(('rock', 'jazz'), (0.9, 0.1)), overrides=()):
    stages = []
    if bpm is not None:
        stages.append(StageResult('bpm', (('engine', 'test-bpm'),), '', (('bpm', bpm),)))
    if energy is not None:
        stages.append(StageResult('energy', (('model', 'emomusic'), ('scale', 'valence_arousal_raw')), '', summary=summary(('valence', 'arousal'), energy)))
    if mood is not None:
        stages.append(StageResult('mood', (('model', 'jamendo-moodtheme'), ('scale', 'mean_score_0_1')), '', summary=summary(mood[0], mood[1])))
    if genres is not None:
        stages.append(StageResult('genres', (('model', 'discogs-effnet'), ('threshold', '0.5')), '', summary=summary(genres[0], genres[1])))
    return ExplorerStoredTrack('sha256:' + suffix * 64, suffix * 64, 10, suffix + '.flac', 1, AnalysisReport('run-' + suffix, 'completed', tuple(stages)), overrides)


class FakeRepo:
    def __init__(self, records): self.records = tuple(records)
    def candidate_snapshot(self): return {'application_id': 1, 'schema_version': 4, 'read_policy': 'bounded_read_transaction'}, self.records


class MoodAxisGraphTests(unittest.TestCase):
    def test_axis_mapping_retains_raw_values_normalized_display_metadata_and_selected_mood(self):
        graph = BuildMoodAxisGraph(FakeRepo([track('a')])).execute('happy')
        node = graph.positioned[0]
        self.assertEqual((node.x.raw, node.y.raw, node.z.raw), (0.25, 0.75, 0.8))
        self.assertEqual((node.x.normalized, node.y.normalized, node.z.normalized), (-0.5, 0.5, 0.6))
        self.assertEqual((node.x.label, node.y.label, node.z.label), ('valence', 'arousal', 'happy'))
        self.assertEqual(node.z.provenance, (('model', 'jamendo-moodtheme'), ('scale', 'mean_score_0_1')))
        self.assertEqual(graph.metadata['coordinate_policy'], 'fixed-mood-axis-v1')
        self.assertIn('happy', graph.available_moods)

    def test_missing_required_axis_data_is_unpositioned_without_zero_fallback(self):
        graph = BuildMoodAxisGraph(FakeRepo([track('a', energy=None), track('b', mood=None)])).execute('happy')
        self.assertEqual(graph.positioned, ())
        reasons = {item.track_id: item.reasons for item in graph.unpositioned}
        self.assertTrue(any('energy: missing valence' in r for r in reasons['sha256:' + 'a' * 64]))
        self.assertTrue(any('mood: missing selected label happy' in r for r in reasons['sha256:' + 'b' * 64]))

    def test_mood_alias_validation_and_unsupported_label_lists_available(self):
        graph = BuildMoodAxisGraph(FakeRepo([track('a', mood=(('happy', 'relaxed'), (0.1, 0.9)))])).execute('Happy')
        self.assertEqual(graph.selected_mood, 'happy')
        with self.assertRaisesRegex(ValueError, 'Unsupported mood label angry; available: happy, relaxed'):
            BuildMoodAxisGraph(FakeRepo([track('a', mood=(('happy', 'relaxed'), (0.1, 0.9)))])).execute('angry')

    def test_filters_bpm_bounds_genre_any_clear_and_coordinates_stable(self):
        graph = BuildMoodAxisGraph(FakeRepo([track('a', bpm=100, genres=(('rock','jazz'), (0.6,0.1))), track('b', bpm=130, genres=(('rock','jazz'), (0.1,0.7)))])).execute('happy')
        filtered = FilterMoodAxisGraph().execute(graph, bpm_min=90, bpm_max=110, genres=('jazz',))
        self.assertEqual([n.track_id for n in filtered.positioned], ['sha256:' + 'b' * 64])
        filtered = FilterMoodAxisGraph().execute(graph, bpm_min=90, bpm_max=110, genres=('rock',))
        self.assertEqual([n.track_id for n in filtered.positioned], ['sha256:' + 'a' * 64])
        cleared = FilterMoodAxisGraph().execute(graph)
        self.assertEqual(tuple((n.track_id, n.x.normalized, n.y.normalized, n.z.normalized) for n in cleared.positioned), tuple((n.track_id, n.x.normalized, n.y.normalized, n.z.normalized) for n in graph.positioned))

    def test_selected_mood_changes_only_z_and_edges_include_axis_independent_explanation(self):
        records = [track('a', mood=(('happy','relaxed'), (0.2,0.9))), track('b', energy=(0.25,0.75), mood=(('happy','relaxed'), (0.7,0.1)))]
        happy = BuildMoodAxisGraph(FakeRepo(records)).execute('happy')
        relaxed = BuildMoodAxisGraph(FakeRepo(records)).execute('relaxed')
        self.assertEqual([(n.x.normalized, n.y.normalized) for n in happy.positioned], [(n.x.normalized, n.y.normalized) for n in relaxed.positioned])
        self.assertNotEqual([n.z.normalized for n in happy.positioned], [n.z.normalized for n in relaxed.positioned])
        self.assertTrue(happy.edges)
        edge = happy.edges[0]
        self.assertIn('axis-independent', edge.explanation)
        self.assertEqual(edge.provenance['policy'], 'symmetric-feature-distance-v1')
        self.assertLessEqual(len(happy.edges), 20)


if __name__ == '__main__':
    unittest.main()
