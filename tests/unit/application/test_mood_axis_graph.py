import unittest
from dataclasses import replace

from music_analyzer.application.dto.analysis import AnalysisReport, StageResult
from music_analyzer.application.dto.catalogue import TrackMetadata
from music_analyzer.application.dto.explorer import ExplorerStoredTrack, MoodAxisEdge
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
    return ExplorerStoredTrack('sha256:' + suffix * 64, suffix * 64, 10, suffix + '.flac', 1, AnalysisReport('run-' + suffix, 'completed', tuple(stages)), overrides, TrackMetadata(duration_seconds=120.0, duration_source='mutagen'))


class FakeRepo:
    def __init__(self, records, *, schema_version=4, graph_status=None, graph_edges=(), positioned_graph_edges=None):
        self.records = tuple(records)
        self.schema_version = schema_version
        self.graph_status = graph_status
        self.graph_edges = tuple(graph_edges)
        self.positioned_graph_edges = tuple(graph_edges if positioned_graph_edges is None else positioned_graph_edges)
    def candidate_snapshot(self): return {'application_id': 1, 'schema_version': self.schema_version, 'read_policy': 'bounded_read_transaction'}, self.records
    def current_graph_edges(self): return self.graph_status, self.graph_edges
    def current_positioned_graph_edges(self, sparse_k=10):
        self.requested_sparse_k = sparse_k
        return self.graph_status, self.positioned_graph_edges


class MoodAxisGraphTests(unittest.TestCase):
    def test_axis_mapping_retains_raw_values_normalized_display_metadata_and_selected_mood(self):
        graph = BuildMoodAxisGraph(FakeRepo([track('a')])).execute('relaxing')
        node = graph.positioned[0]
        self.assertEqual((node.x.raw, node.y.raw, node.z.raw), (0.25, 0.75, 120.0))
        self.assertEqual((node.x.normalized, node.y.normalized, node.z.normalized), (0.25, 0.75, 6.0))
        self.assertEqual((node.x.label, node.y.label, node.z.label), ('valence', 'arousal', 'BPM'))
        self.assertEqual(node.mood_score.raw, 0.8)
        self.assertEqual(node.mood_score.label, 'relaxing')
        self.assertEqual(graph.metadata['coordinate_policy'], 'fixed-valence-arousal-bpm-v1')
        self.assertIn('relaxing', graph.available_moods)

    def test_missing_required_axis_data_is_unpositioned_without_zero_fallback(self):
        graph = BuildMoodAxisGraph(FakeRepo([track('a', energy=None), track('b', bpm=None)])).execute('relaxing')
        self.assertEqual(graph.positioned, ())
        reasons = {item.track_id: item.reasons for item in graph.unpositioned}
        self.assertTrue(any('energy: missing valence' in r for r in reasons['sha256:' + 'a' * 64]))
        self.assertTrue(any('bpm: missing positive finite value' in r for r in reasons['sha256:' + 'b' * 64]))

    def test_incompatible_axis_model_or_out_of_scale_value_is_unpositioned_not_clipped(self):
        base = track('a')
        bad_stages = list(base.run.stages)
        bad_stages[1] = replace(bad_stages[1], provenance=(('other-energy-model', 'synthetic-sha256'),))
        bad_model = replace(base, run=replace(base.run, stages=tuple(bad_stages)))
        out_of_scale = track('b', bpm=float('inf'))
        graph = BuildMoodAxisGraph(FakeRepo([bad_model, out_of_scale])).execute('relaxing')
        self.assertEqual(graph.positioned, ())
        reasons = {item.track_id: item.reasons for item in graph.unpositioned}
        self.assertIn('energy: incompatible model/scale for fixed valence/arousal axis', reasons['sha256:' + 'a' * 64])
        self.assertIn('bpm: missing positive finite value', reasons['sha256:' + 'b' * 64])

    def test_explicit_model_provenance_positions_energy_and_retains_mood_score(self):
        base = track('a')
        models = {'energy': 'emomusic-msd-musicnn-2',
                  'mood': 'mtg_jamendo_moodtheme-discogs-effnet-1'}
        stages = tuple(replace(stage, provenance=(('model', models[stage.stage]), *stage.provenance[1:]))
                       if stage.stage in models else stage for stage in base.run.stages)
        graph = BuildMoodAxisGraph(FakeRepo([replace(base, run=replace(base.run, stages=stages))])).execute('relaxing')
        self.assertEqual(graph.unpositioned, ())
        self.assertEqual((graph.positioned[0].x.raw, graph.positioned[0].y.raw, graph.positioned[0].z.raw),
                         (0.25, 0.75, 120.0))
        self.assertEqual(graph.positioned[0].mood_score.raw, 0.8)

    def test_unrelated_model_names_in_explicit_or_other_provenance_are_not_supported(self):
        base = track('a')
        stages = tuple(replace(stage, provenance=(('model', 'other-' + stage.stage),
                                                    ('source', 'emomusic-msd-musicnn-2' if stage.stage == 'energy'
                                                     else 'mtg_jamendo_moodtheme-discogs-effnet-1')))
                       if stage.stage in ('energy', 'mood') else stage for stage in base.run.stages)
        graph = BuildMoodAxisGraph(FakeRepo([replace(base, run=replace(base.run, stages=stages))])).execute('relaxing')
        self.assertEqual(graph.positioned, ())
        self.assertIn('energy: incompatible model/scale for fixed valence/arousal axis', graph.unpositioned[0].reasons)
        mood_only = tuple(replace(stage, provenance=(('model', 'other-mood'),
                                                      ('source', 'mtg_jamendo_moodtheme-discogs-effnet-1')))
                          if stage.stage == 'mood' else stage for stage in base.run.stages)
        graph = BuildMoodAxisGraph(FakeRepo([replace(base, run=replace(base.run, stages=mood_only))])).execute('relaxing')
        self.assertEqual(len(graph.positioned), 1)
        self.assertIsNone(graph.positioned[0].mood_score)
        conflicting = tuple(replace(stage, provenance=(('model', 'other-energy-model'), *stage.provenance))
                            if stage.stage == 'energy' else stage for stage in base.run.stages)
        graph = BuildMoodAxisGraph(FakeRepo([replace(base, run=replace(base.run, stages=conflicting))])).execute('relaxing')
        self.assertEqual(graph.positioned, ())

    def test_mood_alias_validation_and_unsupported_label_lists_available(self):
        graph = BuildMoodAxisGraph(FakeRepo([track('a', mood=(('relaxing', 'heavy'), (0.1, 0.9)))])).execute('Relaxing')
        self.assertEqual(graph.selected_mood, 'relaxing')
        with self.assertRaisesRegex(ValueError, 'Unsupported mood label angry; available: heavy, relaxing'):
            BuildMoodAxisGraph(FakeRepo([track('a', mood=(('relaxing', 'heavy'), (0.1, 0.9)))])).execute('angry')

    def test_no_supported_mood_returns_all_unpositioned_graph_without_aborting_default_view(self):
        graph = BuildMoodAxisGraph(FakeRepo([track('a', mood=None), track('b', mood=None)])).execute()
        self.assertEqual(graph.selected_mood, '')
        self.assertEqual(graph.available_moods, ())
        self.assertEqual(len(graph.positioned), 2)
        self.assertTrue(all(n.mood_score is None for n in graph.positioned))
        self.assertEqual({item.track_id for item in graph.unpositioned}, set())
        with self.assertRaisesRegex(ValueError, 'Unsupported mood label angry; available: none'):
            BuildMoodAxisGraph(FakeRepo([track('a', mood=None)])).execute('angry')

    def test_selected_label_missing_or_overridden_never_removes_positioned_track(self):
        records = [track('a', mood=(('relaxing',), (0.4,))), track('b', overrides=(('mood', 'user text'),))]
        graph = BuildMoodAxisGraph(FakeRepo(records)).execute('relaxing')
        self.assertEqual(len(graph.positioned), 2)
        self.assertIsNone(graph.positioned[1].mood_score)
        self.assertEqual(graph.positioned[0].mood_score.raw, 0.4)
        heavy = BuildMoodAxisGraph(FakeRepo(records + [track('c', mood=(('heavy',), (0.9,)))])).execute('heavy')
        self.assertEqual({n.track_id for n in heavy.positioned}, {r.track_id for r in records + [track('c')]})
        self.assertIsNone(heavy.positioned[0].mood_score)

    def test_missing_and_overridden_bpm_are_not_positioned(self):
        graph = BuildMoodAxisGraph(FakeRepo([track('a', bpm=None), track('b', bpm=0), track('c', bpm='NaN'), track('d', overrides=(('bpm', 'fast'),))])).execute()
        self.assertEqual(graph.positioned, ())
        self.assertEqual(len(graph.unpositioned), 4)

    def test_filters_bpm_bounds_genre_any_clear_and_coordinates_stable(self):
        graph = BuildMoodAxisGraph(FakeRepo([track('a', bpm=100, genres=(('rock','jazz'), (0.6,0.2))), track('b', bpm=130, genres=(('rock','jazz'), (0.1,0.7)))])).execute('relaxing')
        filtered = FilterMoodAxisGraph().execute(graph, bpm_min=90, bpm_max=110, genres=('jazz',))
        self.assertEqual([n.track_id for n in filtered.positioned], ['sha256:' + 'a' * 64])
        filtered = FilterMoodAxisGraph().execute(graph, bpm_min=90, bpm_max=110, genres=('rock',))
        self.assertEqual([n.track_id for n in filtered.positioned], ['sha256:' + 'a' * 64])
        cleared = FilterMoodAxisGraph().execute(graph)
        self.assertEqual(tuple((n.track_id, n.x.normalized, n.y.normalized, n.z.normalized) for n in cleared.positioned), tuple((n.track_id, n.x.normalized, n.y.normalized, n.z.normalized) for n in graph.positioned))

    def test_v7_warm_graph_requires_exact_positioned_v8_rebuild_without_approximation(self):
        records = [track('a'), track('b')]
        edge = MoodAxisEdge(records[0].track_id, records[1].track_id, 0.42, 'persisted explanation', {'policy': 'symmetric-feature-distance-v1'}, 2)
        graph = BuildMoodAxisGraph(FakeRepo(records, schema_version=7, graph_status={'state': 'ready', 'source': 'graph_build_edges'}, graph_edges=(edge,))).execute('relaxing')
        self.assertEqual(graph.edges, ())
        self.assertEqual(graph.metadata['graph_status']['state'], 'build_needed')
        self.assertIn('schema v8 rebuild', graph.metadata['graph_status']['reason'])

    def test_v8_graph_uses_exact_persisted_positioned_edges_and_exposes_ready_status(self):
        records = [track('a'), track('b')]
        edge = MoodAxisEdge(records[0].track_id, records[1].track_id, 0.42, 'persisted explanation', {'policy': 'symmetric-feature-distance-v1'}, 2)
        graph = BuildMoodAxisGraph(FakeRepo(records, schema_version=8, graph_status={'state': 'ready', 'source': 'graph_build_positioned_edges', 'sparse_k': 10}, positioned_graph_edges=(edge,))).execute('relaxing')
        self.assertEqual(graph.edges, (edge,))
        self.assertEqual(graph.metadata['graph_status']['state'], 'ready')
        self.assertEqual(graph.metadata['graph_status']['source'], 'graph_build_positioned_edges')

    def test_v8_stale_graph_reports_status_without_edges(self):
        records = [track('a'), track('b')]
        graph = BuildMoodAxisGraph(FakeRepo(records, schema_version=8, graph_status={'state': 'stale', 'action': 'run music-analyzer graph build --database DB'}, positioned_graph_edges=(MoodAxisEdge(records[0].track_id, records[1].track_id, 0.42, 'old', {}, 1),))).execute('relaxing')
        self.assertEqual(graph.edges, ())
        self.assertEqual(graph.metadata['graph_status']['state'], 'stale')
        self.assertIn('music-analyzer graph build --database', graph.metadata['graph_status']['action'])

    def test_v8_sparse_k_mismatch_reports_build_needed_without_serving_wrong_degree(self):
        records = [track('a'), track('b')]
        edge = MoodAxisEdge(records[0].track_id, records[1].track_id, 0.42, 'persisted explanation', {'policy': 'symmetric-feature-distance-v1'}, 2)
        graph = BuildMoodAxisGraph(FakeRepo(records, schema_version=8, graph_status={'state': 'ready', 'source': 'graph_build_positioned_edges', 'sparse_k': 1}, positioned_graph_edges=(edge,)), sparse_k=10).execute('relaxing')
        self.assertEqual(graph.edges, ())
        self.assertEqual(graph.metadata['graph_status']['state'], 'stale')
        self.assertIn('sparse_k', graph.metadata['graph_status']['reason'])

    def test_v8_ready_graph_preserves_exact_positioned_subset_topology_for_all_mood_selections(self):
        records = [
            track('a', energy=(0.10, 0.00), mood=(('relaxing', 'heavy'), (0.8, 0.2))),
            track('b', energy=(0.10, 0.20), mood=(('relaxing', 'heavy'), (0.7, 0.3))),
            track('c', bpm=None, energy=(0.10, 0.10), mood=(('relaxing', 'heavy'), (0.6, 0.4))),
        ]
        exact_positioned_edge = MoodAxisEdge(
            records[0].track_id,
            records[1].track_id,
            0.95,
            'axis-independent relatedness from persisted exact positioned graph_build_positioned_edges snapshot',
            {'policy': 'symmetric-feature-distance-v1', 'source': 'graph_build_positioned_edges'},
            1,
        )
        warm_repo = FakeRepo(
            records,
            schema_version=8,
            graph_status={'state': 'ready', 'source': 'graph_build_positioned_edges', 'sparse_k': 1},
            positioned_graph_edges=(exact_positioned_edge,),
        )
        cold_repo = FakeRepo(records, schema_version=6)

        for selection in (None, 'relaxing', 'heavy'):
            with self.subTest(selection=selection):
                exact = BuildMoodAxisGraph(cold_repo, sparse_k=1).execute(selection).edges
                warm = BuildMoodAxisGraph(warm_repo, sparse_k=1).execute(selection).edges

                self.assertEqual(tuple((edge.a, edge.b) for edge in exact), ((records[0].track_id, records[1].track_id),))
                self.assertEqual(tuple((edge.a, edge.b) for edge in warm), tuple((edge.a, edge.b) for edge in exact))

    def test_selected_mood_changes_only_optional_score_and_edges_include_axis_independent_explanation(self):
        records = [track('a', mood=(('relaxing','heavy'), (0.2,0.9))), track('b', energy=(0.25,0.75), mood=(('relaxing','heavy'), (0.7,0.1)))]
        relaxing = BuildMoodAxisGraph(FakeRepo(records)).execute('relaxing')
        heavy = BuildMoodAxisGraph(FakeRepo(records)).execute('heavy')
        self.assertEqual([(n.x.normalized, n.y.normalized) for n in relaxing.positioned], [(n.x.normalized, n.y.normalized) for n in heavy.positioned])
        self.assertEqual([(n.track_id, n.x, n.y, n.z) for n in relaxing.positioned], [(n.track_id, n.x, n.y, n.z) for n in heavy.positioned])
        self.assertNotEqual([n.mood_score.raw for n in relaxing.positioned], [n.mood_score.raw for n in heavy.positioned])
        self.assertEqual(relaxing.edges, heavy.edges)
        self.assertTrue(relaxing.edges)
        edge = relaxing.edges[0]
        self.assertIn('axis-independent', edge.explanation)
        self.assertEqual(edge.provenance['policy'], 'symmetric-feature-distance-v1')
        self.assertLessEqual(len(relaxing.edges), 20)


if __name__ == '__main__':
    unittest.main()
