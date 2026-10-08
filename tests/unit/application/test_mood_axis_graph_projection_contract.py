"""Public, synthetic warm-projection preservation oracle shared by both mirrors.

Expected values are literals, not a cold graph or the other implementation's
output. Summary extrema deliberately differ from means; diagnostic uncertainty
and provisional flags deliberately differ between stages.
"""
import unittest
from dataclasses import asdict
from types import SimpleNamespace

from music_analyzer.application.dto.analysis import AnalysisReport, StageResult
from music_analyzer.application.dto.catalogue import TrackMetadata
from music_analyzer.application.dto import explorer as analyzer_dto
from music_analyzer.application.use_cases import explorer as analyzer
from music_analyzer.domain.analysis import ScoreSummary
from music_explorer.application.dto import explorer as standalone_dto
from music_explorer.application.use_cases import explorer as standalone


MIRRORS = (
    ('analyzer', analyzer, SimpleNamespace(
        AnalysisReport=AnalysisReport, StageResult=StageResult,
        TrackMetadata=TrackMetadata, ScoreSummary=ScoreSummary,
        ExplorerStoredTrack=analyzer_dto.ExplorerStoredTrack,
        MoodAxisEdge=analyzer_dto.MoodAxisEdge)),
    ('standalone', standalone, standalone_dto),
)
ENERGY_PROVENANCE = (('model', 'emomusic-msd-musicnn-2'), ('sha256', 'public-energy'), ('note', 'énergie 日本'))
MOOD_PROVENANCE = (('model', 'mtg_jamendo_moodtheme-discogs-effnet-1'), ('sha256', 'public-mood'))
BPM_PROVENANCE = (('engine', 'public-bpm'), ('note', '拍'))
STATUS = {'state': 'ready', 'source': 'graph_build_positioned_edges', 'sparse_k': 2, 'build_id': 'public-构建', 'source_revision': 'public-r1'}


class WarmRepository:
    def __init__(self, dto):
        def record(identity, label, mood_labels=('dream-pop', '夜'), mood_values=(0.625, 0.25), overrides=()):
            stages = (
                dto.StageResult('bpm', BPM_PROVENANCE, 'tempo ±拍', (('bpm', 140.0),)),
                dto.StageResult('energy', ENERGY_PROVENANCE, 'energy sampled only', summary=dto.ScoreSummary(
                    ('valence', 'arousal'), (-0.25, 1.25), (-0.75, 0.5), (0.5, 1.75), 0.625, False, 'summary énergie uncertainty')),
                dto.StageResult('mood', MOOD_PROVENANCE, 'mood 未校准', summary=dto.ScoreSummary(
                    mood_labels, mood_values, tuple(v - 0.125 for v in mood_values), tuple(v + 0.125 for v in mood_values),
                    0.75, True, 'summary mood uncertainty')),
                dto.StageResult('genres', (('model', 'public-genre'), ('threshold', '0.7')), '', summary=dto.ScoreSummary(
                    ('摇滚', 'ambient'), (0.875, 0.125), (0.5, 0.0), (1.0, 0.5), 0.5, False, 'summary genres uncertainty')),
            )
            return dto.ExplorerStoredTrack(identity, 'public-' + identity, 123, label, 1,
                                           dto.AnalysisReport('shared-public-run', 'completed', stages), overrides,
                                           dto.TrackMetadata(duration_seconds=42.5, duration_source='mutagen'))
        # First positioned row must not dictate the default. The unpositioned
        # record supplies the lexically first label, even with a score > 1.
        self.records = (
            record('z', 'Zéro 🎵.flac'), record('a', '日本.flac'), record('b', 'B.flac'),
            record('u', '未定位.flac', ('00-outside', '夜'), (1.5, 0.25), (('bpm', '手動 tempo'),)),
            record('o', 'Override.flac', ('00-hidden',), (0.875,), (('mood', '夢 manual'),)),
        )
        # Equal stored scores retain supplied order and full precision. All
        # displayed coordinates are identical; no displayed-subset nearest
        # neighbour computation may replace this deliberately sparse topology.
        self.edges = (
            dto.MoodAxisEdge('z', 'b', 0.123456789, 'stored tie β', {'source': 'graph_build_positioned_edges', 'tie': 'β'}, 3),
            dto.MoodAxisEdge('z', 'a', 0.123456789, 'stored tie α', {'source': 'graph_build_positioned_edges', 'tie': 'α'}, 2),
            dto.MoodAxisEdge('z', 'u', 0.999, 'ineligible endpoint', {'source': 'public'}, 4),
            dto.MoodAxisEdge('z', 'absent', 0.998, 'absent endpoint', {'source': 'public'}, 4),
        )
        self.requested_k = None

    def candidate_snapshot(self):
        return {'application_id': 77, 'schema_version': 10, 'read_policy': 'bounded_read_transaction'}, self.records

    def current_positioned_graph_edges(self, sparse_k=10):
        self.requested_k = sparse_k
        return dict(STATUS), self.edges

    def current_graph_edges(self):
        raise AssertionError('global edges are not the positioned warm authority')


def literal_graph(selected):
    """One literal DTO oracle; only selected optional strip changes by mood."""
    def node(identity, label, overridden=False):
        return {
            'track_id': identity, 'display_label': label,
            'x': {'label': 'valence', 'raw': -0.25, 'normalized': -0.25, 'scale': 'native-emomusic-valence-regression', 'provenance': ENERGY_PROVENANCE},
            'y': {'label': 'arousal', 'raw': 1.25, 'normalized': 1.25, 'scale': 'native-emomusic-arousal-regression', 'provenance': ENERGY_PROVENANCE},
            'z': {'label': 'BPM', 'raw': 140.0, 'normalized': 7.0, 'scale': 'fixed-BPM/20-display-units', 'provenance': BPM_PROVENANCE},
            'bpm': 140.0, 'genres': (('ambient', 0.125), ('摇滚', 0.875)),
            'reasons': ('bpm: tempo ±拍', 'key: missing result', 'mood: mood 未校准', 'mood: provisional, uncalibrated scores', 'instruments: missing result', 'energy: energy sampled only'),
            'genre_threshold': 0.7,
            'mood_score': None if selected == '00-outside' or overridden else {
                'label': 'dream-pop', 'raw': 0.625, 'normalized': 0.625,
                'scale': 'sigmoid-score-[0,1]', 'provenance': MOOD_PROVENANCE},
        }
    return {
        'metadata': {
            'application_id': 77, 'schema_version': 10, 'read_policy': 'bounded_read_transaction', 'track_count': 5,
            'coordinate_policy': 'fixed-valence-arousal-bpm-v1',
            'normalization_policy': 'native-energy-and-fixed-bpm-20-per-unit-v1',
            'energy_scale': 'Emomusic native valence/arousal regression coordinates retained when model provenance is compatible; no arbitrary clipping or DJ-energy interpretation',
            'bpm_scale': 'Raw positive finite BPM, fixed display transform BPM / 20 (20 BPM per normalized unit); never octave-coerced or sample-refitted',
            'mood_scale': 'Optional selected Jamendo mood/theme sigmoid labelled mean score on fixed [0,1] strip only; never a coordinate or visibility condition',
            'genre_filter_policy': 'ANY selected genre with finite retained mean score > 0.1 (detail display cutoff, not provisional classification cutoff)',
            'edge_policy': 'endpoint-local-exact-top-k-neighbours-v2', 'distance_policy': 'symmetric-feature-distance-v1',
            'sparse_k': 2, 'graph_status': {'state': 'ready', 'source': 'graph_build_positioned_edges', 'sparse_k': 2, 'build_id': 'public-构建', 'source_revision': 'public-r1'},
        },
        'selected_mood': selected, 'available_moods': ('00-outside', 'dream-pop', '夜'),
        'positioned': (node('z', 'Zéro 🎵.flac'), node('a', '日本.flac'), node('b', 'B.flac'), node('o', 'Override.flac', True)),
        'unpositioned': ({'track_id': 'u', 'display_label': '未定位.flac', 'reasons': ('bpm: missing positive finite value',)},),
        'edges': (
            {'a': 'z', 'b': 'b', 'score': 0.123456789, 'explanation': 'stored tie β', 'provenance': {'source': 'graph_build_positioned_edges', 'tie': 'β'}, 'supported_group_count': 3},
            {'a': 'z', 'b': 'a', 'score': 0.123456789, 'explanation': 'stored tie α', 'provenance': {'source': 'graph_build_positioned_edges', 'tie': 'α'}, 'supported_group_count': 2},
        ),
    }


class MoodAxisGraphProjectionContractTests(unittest.TestCase):
    def test_warm_graph_all_dto_fields_match_literal_for_default_and_alias(self):
        for name, application, dto in MIRRORS:
            for requested, selected in ((None, '00-outside'), ('', '00-outside'), (' Dream_POP ', 'dream-pop')):
                with self.subTest(mirror=name, requested=requested):
                    repository = WarmRepository(dto)
                    graph = application.BuildMoodAxisGraph(repository, sparse_k=2).execute(requested)
                    self.assertEqual(asdict(graph), literal_graph(selected))
                    self.assertEqual(repository.requested_k, 2)

    def test_warm_projection_leaves_source_diagnostics_available_to_other_consumers(self):
        # Graph DTOs do not expose summary extrema, coverage or summary-level
        # uncertainty. This companion preservation check is about the source
        # evidence, not a claim that those fields are rendered by the graph.
        expected = (
            {'labels': ('valence', 'arousal'), 'mean': (-0.25, 1.25),
             'minimum': (-0.75, 0.5), 'maximum': (0.5, 1.75),
             'coverage': 0.625, 'provisional': False, 'uncertainty': 'summary énergie uncertainty'},
            {'labels': ('dream-pop', '夜'), 'mean': (0.625, 0.25),
             'minimum': (0.5, 0.125), 'maximum': (0.75, 0.375),
             'coverage': 0.75, 'provisional': True, 'uncertainty': 'summary mood uncertainty'},
            {'labels': ('摇滚', 'ambient'), 'mean': (0.875, 0.125),
             'minimum': (0.5, 0.0), 'maximum': (1.0, 0.5),
             'coverage': 0.5, 'provisional': False, 'uncertainty': 'summary genres uncertainty'},
        )
        for name, application, dto in MIRRORS:
            with self.subTest(mirror=name):
                repository = WarmRepository(dto)
                application.BuildMoodAxisGraph(repository, sparse_k=2).execute('dream-pop')
                self.assertEqual(tuple(asdict(stage.summary) for stage in repository.records[0].run.stages
                                       if stage.summary is not None), expected)

    def test_unsupported_mood_lists_sorted_labels_including_unpositioned_not_override(self):
        for name, application, dto in MIRRORS:
            with self.subTest(mirror=name):
                with self.assertRaisesRegex(ValueError, '^Unsupported mood label 00-hidden; available: 00-outside, dream-pop, 夜$'):
                    application.BuildMoodAxisGraph(WarmRepository(dto), sparse_k=2).execute('00-hidden')


if __name__ == '__main__':
    unittest.main()
