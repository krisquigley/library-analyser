import unittest

from music_analyzer.application.dto.analysis import AnalysisReport, StageResult
from music_analyzer.application.dto.catalogue import TrackMetadata
from music_analyzer.application.dto.explorer import ExplorerStoredTrack
from music_analyzer.application.use_cases.build_graph import BuildGraphSnapshot, _source_fingerprint
from music_analyzer.application.use_cases.candidates import _features
from music_analyzer.domain.analysis import ScoreSummary
from music_analyzer.domain.projection import _bounded_edges


def _summary(labels, values):
    return ScoreSummary(tuple(labels), tuple(values), tuple(values), tuple(values), 1.0, False, '')


def _track(suffix, *, bpm, energy, mood, genres, available_locations=1, status='completed', duration=180.0):
    stages = (
        StageResult('bpm', (('model', 'fixture-bpm'),), '', (('bpm', bpm),)),
        StageResult('energy', (('model', 'emomusic-msd-musicnn-2'), ('scale', 'native_valence_arousal_regression')), '', summary=_summary(('valence', 'arousal'), energy)),
        StageResult('mood', (('model', 'mtg_jamendo_moodtheme-discogs-effnet-1'), ('scale', 'sigmoid_mean_score_0_1')), '', summary=_summary(('relaxing', 'heavy'), mood)),
        StageResult('genres', (('model', 'genre_discogs400-discogs-effnet-1'), ('threshold', '0.5')), '', summary=_summary(('rock', 'jazz'), genres)),
        StageResult('key', (('model', 'fixture-key'),), '', (('key', 'C major'),)),
    )
    run = AnalysisReport('run-' + suffix, status, stages, '')
    return ExplorerStoredTrack(
        'sha256:' + suffix * 64,
        suffix * 64,
        100 + ord(suffix),
        suffix + '.flac',
        available_locations,
        run,
        (('bpm', str(bpm)), ('title', 'graph-irrelevant title')),
        TrackMetadata(duration_seconds=duration, duration_source='mutagen'),
        ('/music/' + suffix + '.flac',),
    )


class CompactGraphSourceReader:
    def __init__(self, records):
        self.records = tuple(sorted(records, key=lambda record: record.track_id))
        self.stream_calls = 0

    def graph_source_tracks(self):
        self.stream_calls += 1
        for record in self.records:
            yield record

    def candidate_snapshot(self):
        raise AssertionError('candidate_snapshot must not be used by graph build compact source reads')


class CapturingGraphWriter:
    def __init__(self):
        self.revision = 'source-revision-from-streamed-writer'
        self.replaced = None

    def source_revision(self):
        return self.revision

    def begin_graph_build(self, sparse_k, source_revision):
        self.claim = (sparse_k, source_revision)
        return 'attempt-1'

    def replace_graph_snapshot(self, edges, sparse_k, source_fingerprint, positioned_edges=(), *, source_revision=None, attempt_id=None):
        self.replaced = {
            'edges': tuple(edges),
            'sparse_k': sparse_k,
            'source_fingerprint': source_fingerprint,
            'positioned_edges': tuple(positioned_edges),
            'source_revision': source_revision,
            'attempt_id': attempt_id,
        }

    def finish_graph_build_attempt(self, build_id, status, detail):  # pragma: no cover - regression diagnostics only
        self.finished = (build_id, status, detail)


class GraphBuildCompactSourceRedTests(unittest.TestCase):
    def test_graph_build_streams_compact_source_tracks_without_eager_candidate_snapshot(self):
        retained = (
            _track('a', bpm=100.0, energy=(0.1, 0.2), mood=(0.9, 0.1), genres=(0.9, 0.1)),
            _track('b', bpm=130.0, energy=(0.2, 0.7), mood=(0.4, 0.6), genres=(0.2, 0.8)),
            _track('c', bpm=170.0, energy=(0.8, 0.3), mood=(0.2, 0.8), genres=(0.7, 0.3)),
        )
        ignored = (
            _track('d', bpm=90.0, energy=(0.3, 0.3), mood=(0.5, 0.5), genres=(0.5, 0.5), available_locations=0),
            _track('e', bpm=110.0, energy=(0.4, 0.4), mood=(0.6, 0.4), genres=(0.4, 0.6), status='failed'),
            _track('f', bpm=120.0, energy=(0.5, 0.5), mood=(0.7, 0.3), genres=(0.3, 0.7), duration=None),
        )
        reader = CompactGraphSourceReader((*reversed(retained), *ignored))
        writer = CapturingGraphWriter()

        result = BuildGraphSnapshot(reader, writer, sparse_k=2).execute()

        expected_features = tuple(_features(record) for record in retained)
        expected_edges = tuple(_bounded_edges(expected_features, 2))
        expected_fingerprint = _source_fingerprint(retained)
        self.assertEqual(result.edge_count, len(expected_edges))
        self.assertEqual(result.source_fingerprint, expected_fingerprint)
        self.assertEqual(writer.replaced['edges'], expected_edges)
        self.assertEqual(writer.replaced['positioned_edges'], expected_edges)
        self.assertEqual(writer.replaced['source_fingerprint'], expected_fingerprint)
        self.assertEqual(writer.replaced['source_revision'], writer.revision)
        self.assertEqual(writer.replaced['attempt_id'], 'attempt-1')
        self.assertEqual(reader.stream_calls, 1)


if __name__ == '__main__':
    unittest.main()
