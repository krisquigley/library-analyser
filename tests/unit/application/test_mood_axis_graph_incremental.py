"""Warm projection must consume each record before requesting the next one.

The producer is finite: its progress check fails immediately rather than
blocking or manufacturing a memory/time threshold. Instrumented tuples keep
normal DTO data shapes and observe reads of display metadata and BPM evidence,
not calls to any private mapping function.
"""
import importlib
import unittest


class ObservedTuple(tuple):
    def __new__(cls, values, consumed):
        result = super().__new__(cls, values)
        result.consumed = consumed
        return result

    def __iter__(self):
        self.consumed()
        return super().__iter__()


class ProgressAwareRecords:
    def __init__(self, records, progress):
        self.records = records
        self.progress = progress
        self.requested = []

    def __iter__(self):
        for index, record in enumerate(self.records):
            if index:
                previous = self.records[index - 1]
                observed = self.progress[previous.track_id]
                if observed != {'display_metadata', 'bpm_evidence'}:
                    raise AssertionError(
                        'next record requested before previous record was mapped: '
                        + previous.track_id + '; observed=' + repr(sorted(observed))
                    )
            self.requested.append(record.track_id)
            yield record


class WarmRepository:
    def __init__(self, records):
        self.records = records
        self.requested_sparse_k = None

    def candidate_snapshot(self):
        return {
            'application_id': 1,
            'schema_version': 8,
            'read_policy': 'bounded_read_transaction',
        }, self.records

    def current_positioned_graph_edges(self, sparse_k=10):
        self.requested_sparse_k = sparse_k
        return {
            'state': 'ready',
            'source': 'graph_build_positioned_edges',
            'sparse_k': sparse_k,
        }, ()


def fixture(package):
    explorer = importlib.import_module(package + '.application.dto.explorer')
    if package == 'music_analyzer':
        analysis = importlib.import_module(package + '.application.dto.analysis')
        catalogue = importlib.import_module(package + '.application.dto.catalogue')
        domain = importlib.import_module(package + '.domain.analysis')
    else:
        analysis = catalogue = domain = explorer
    progress = {}
    records = []
    for suffix, label, bpm, valence, arousal in (
        ('a', 'relaxing', 100.0, 0.25, 0.75),
        ('b', 'heavy', 140.0, 0.5, 0.125),
    ):
        track_id = 'sha256:' + suffix * 64
        observed = progress[track_id] = set()
        bpm_values = ObservedTuple(
            (('bpm', bpm),),
            lambda observed=observed: observed.add('bpm_evidence'),
        )
        common = ObservedTuple(
            (('title', 'Title ' + suffix), ('artist', 'Artist')),
            lambda observed=observed: observed.add('display_metadata'),
        )
        stages = (
            analysis.StageResult('bpm', (('engine', 'test-bpm'),), '', bpm_values),
            analysis.StageResult(
                'energy',
                (('emomusic-msd-musicnn-2', 'synthetic-sha256'),),
                '',
                summary=domain.ScoreSummary(
                    ('valence', 'arousal'), (valence, arousal),
                    (valence, arousal), (valence, arousal), 1.0, False, '',
                ),
            ),
            analysis.StageResult(
                'mood',
                (('mtg_jamendo_moodtheme-discogs-effnet-1', 'synthetic-sha256'),),
                '',
                summary=domain.ScoreSummary(
                    (label,), (0.8,), (0.8,), (0.8,), 1.0, False, '',
                ),
            ),
        )
        records.append(explorer.ExplorerStoredTrack(
            track_id, suffix * 64, 10, suffix + '.flac', 1,
            analysis.AnalysisReport('run-' + suffix, 'completed', stages), (),
            catalogue.TrackMetadata(
                common=common, duration_seconds=120.0, duration_source='mutagen',
            ),
        ))
    return ProgressAwareRecords(tuple(records), progress), progress


class MoodAxisGraphIncrementalTests(unittest.TestCase):
    def assert_incremental_warm_projection(self, package):
        use_cases = importlib.import_module(package + '.application.use_cases.explorer')
        records, progress = fixture(package)
        repository = WarmRepository(records)

        graph = use_cases.BuildMoodAxisGraph(repository).execute()

        expected_ids = ('sha256:' + 'a' * 64, 'sha256:' + 'b' * 64)
        self.assertEqual(records.requested, list(expected_ids))
        self.assertEqual(progress, {
            track_id: {'display_metadata', 'bpm_evidence'}
            for track_id in expected_ids
        })
        self.assertEqual(tuple(node.track_id for node in graph.positioned), expected_ids)
        self.assertEqual(
            tuple((node.x.raw, node.y.raw, node.z.raw) for node in graph.positioned),
            ((0.25, 0.75, 100.0), (0.5, 0.125, 140.0)),
        )
        # The second record supplies the default label: incremental mapping
        # must not prematurely resolve the default from the first record.
        self.assertEqual(graph.available_moods, ('heavy', 'relaxing'))
        self.assertEqual(graph.selected_mood, 'heavy')
        self.assertIsNone(graph.positioned[0].mood_score)
        self.assertEqual(graph.positioned[1].mood_score.raw, 0.8)
        self.assertEqual(graph.unpositioned, ())
        self.assertEqual(graph.edges, ())
        self.assertEqual(graph.metadata['track_count'], 2)
        self.assertEqual(graph.metadata['graph_status']['state'], 'ready')
        self.assertEqual(repository.requested_sparse_k, 10)

    def test_analyzer_maps_first_warm_record_before_requesting_next(self):
        self.assert_incremental_warm_projection('music_analyzer')

    def test_standalone_maps_first_warm_record_before_requesting_next(self):
        self.assert_incremental_warm_projection('music_explorer')


if __name__ == '__main__':
    unittest.main()
