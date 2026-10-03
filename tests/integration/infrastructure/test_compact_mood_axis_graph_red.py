import tempfile
import unittest
from pathlib import Path

from music_analyzer.application.dto.analysis import AudioSource, StageResult
from music_analyzer.application.dto.catalogue import Inventory, ScannedFile, TrackMetadata
from music_analyzer.application.use_cases.explorer import BuildMoodAxisGraph
from music_analyzer.domain.analysis import ScoreSummary
from music_analyzer.domain.catalogue import FileIdentity
from music_analyzer.domain.projection import ProjectionEdge
from music_analyzer.infrastructure.persistence.analysis import SQLiteAnalysisRepository
from music_analyzer.infrastructure.persistence.explorer_readonly import ReadOnlyExplorerSQLiteRepository


def summary(labels, values, provisional=True):
    return ScoreSummary(tuple(labels), tuple(values), tuple(values), tuple(values), 1.0, provisional, '')


def add_positioned_track(repository, suffix, *, bpm=120.0, genres=(('rock', 'jazz'), (0.9, 0.1)), mood=(('relaxing', 'heavy'), (0.8, 0.2))):
    identity = FileIdentity(suffix * 64, 10)
    location = f'/music/{suffix}.flac'
    repository.register(Inventory('/music', (
        ScannedFile(location, identity, 1, 'flac', TrackMetadata(duration_seconds=120.0, duration_source='mutagen')),
    ), (), False))
    run_id = repository.start(AudioSource(location, identity.track_id))
    repository.save_stage(run_id, StageResult('bpm', (('engine', 'test-bpm'),), '', (('bpm', bpm),)))
    repository.save_stage(run_id, StageResult(
        'energy',
        (('emomusic-msd-musicnn-2', 'synthetic-sha256'), ('scale', 'native_valence_arousal_regression')),
        '',
        summary=summary(('valence', 'arousal'), (0.25, 0.75)),
    ))
    repository.save_stage(run_id, StageResult(
        'mood',
        (('mtg_jamendo_moodtheme-discogs-effnet-1', 'synthetic-sha256'), ('scale', 'sigmoid_mean_score_0_1')),
        '',
        summary=summary(mood[0], mood[1]),
    ))
    repository.save_stage(run_id, StageResult(
        'genres',
        (('genre_discogs400-discogs-effnet-1', 'synthetic-sha256'), ('threshold', '0.5')),
        '',
        summary=summary(genres[0], genres[1]),
    ))
    repository.finish(run_id, 'completed', '')
    return identity.track_id


class CompactMoodAxisGraphReadTests(unittest.TestCase):
    def test_warm_v8_endpoint_uses_compact_reader_without_per_track_hydration(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'analysis.sqlite'
            writer = SQLiteAnalysisRepository(str(path))
            first = add_positioned_track(writer, 'a')
            second = add_positioned_track(writer, 'b', bpm=128.0, genres=(('rock', 'jazz'), (0.05, 0.8)))
            writer.replace_graph_snapshot(
                (ProjectionEdge(first, second, 0.25, 2),),
                10,
                'synthetic-compact-red',
                positioned_edges=(ProjectionEdge(first, second, 0.25, 2),),
            )
            repo = ReadOnlyExplorerSQLiteRepository(str(path))

            def fail_per_track_read(*args, **kwargs):
                raise AssertionError('_read_track should not be called by the warm v8 compact mood-axis graph path')

            repo._read_track = fail_per_track_read

            graph = BuildMoodAxisGraph(repo).execute('relaxing')

            self.assertEqual(tuple(node.track_id for node in graph.positioned), (first, second))
            self.assertEqual(tuple((edge.a, edge.b, edge.score) for edge in graph.edges), ((first, second, 0.75),))
            self.assertEqual(graph.metadata['graph_status']['state'], 'ready')
            self.assertEqual(graph.metadata['graph_status']['source'], 'graph_build_positioned_edges')


if __name__ == '__main__':
    unittest.main()
