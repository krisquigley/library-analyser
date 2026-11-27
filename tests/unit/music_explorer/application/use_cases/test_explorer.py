"""The mood-axis graph's nodes (#291): each carries the track's key, the listener's override first."""
import unittest

from music_explorer.application.dto.explorer import AnalysisReport, ExplorerStoredTrack, ScoreSummary, StageResult
from music_explorer.application.use_cases.explorer import BuildMoodAxisGraph


def summary(labels, values):
    return ScoreSummary(tuple(labels), tuple(values), tuple(values), tuple(values), 1.0)


def track(suffix, key=None, overrides=()):
    stages = [StageResult('bpm', (('engine', 'test-bpm'),), '', (('bpm', 120.0),)),
              StageResult('energy', (('emomusic-msd-musicnn-2', 'synthetic-sha256'),), '',
                          summary=summary(('valence', 'arousal'), (0.25, 0.75)))]
    if key is not None:
        stages.append(StageResult('key', (('engine', 'test-key'),), '', key))
    return ExplorerStoredTrack('sha256:' + suffix * 64, suffix * 64, 10, suffix + '.flac', 1,
                               AnalysisReport('run-' + suffix, 'completed', tuple(stages)), overrides)


class SnapshotRepository:
    def __init__(self, records, schema_version):
        self.records, self.schema_version = tuple(records), schema_version

    def candidate_snapshot(self):
        return {'application_id': 1, 'schema_version': self.schema_version}, self.records

    def current_graph_edges(self):
        return None, ()

    def current_positioned_graph_edges(self, sparse_k=10):
        return {'state': 'ready'}, ()


class MoodAxisGraphKeyTests(unittest.TestCase):
    def keys(self, schema_version):
        records = [track('a', (('key', 'A'), ('scale', 'minor'), ('strength', 0.8))),
                   track('b', (('key', 'Eb'), ('scale', 'major'), ('strength', 0.2))),
                   track('c'),
                   track('d', (('key', 'A'),)),
                   track('e', (('key', 'C'), ('scale', 'major')), overrides=(('key', 'D minor'),))]
        graph = BuildMoodAxisGraph(SnapshotRepository(records, schema_version)).execute()
        return {node.track_id[7]: node.key for node in graph.positioned}

    def test_each_node_carries_its_tracks_key_or_none(self):
        for schema_version in (4, 8):
            with self.subTest(schema_version=schema_version):
                self.assertEqual(self.keys(schema_version), {
                    'a': 'A minor', 'b': 'Eb major', 'c': None, 'd': None, 'e': 'D minor'})


if __name__ == '__main__':
    unittest.main()
