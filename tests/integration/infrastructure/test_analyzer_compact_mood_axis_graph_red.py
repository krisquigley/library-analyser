from contextlib import closing
import sqlite3
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
    repository.save_stage(run_id, StageResult('key', (('engine', 'test-key'),), '', (('key', 'C major'),)))
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


class AnalyzerCompactMoodAxisGraphReadTests(unittest.TestCase):
    def test_mood_axis_graph_uses_compact_evidence_without_decoding_raw_stages(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'analysis.sqlite'
            writer = SQLiteAnalysisRepository(str(path))
            first = add_positioned_track(writer, 'a')
            second = add_positioned_track(writer, 'b', bpm=128.0, genres=(('rock', 'jazz'), (0.05, 0.8)))
            writer.replace_graph_snapshot(
                (ProjectionEdge(first, second, 0.25, 2),),
                10,
                'synthetic-analyzer-compact-red',
                positioned_edges=(ProjectionEdge(first, second, 0.25, 2),),
            )
            repo = ReadOnlyExplorerSQLiteRepository(str(path))

            def fail_raw_stage_decode(*args, **kwargs):
                raise AssertionError('_stage_from_payload should not be called for tracks with current compact graph_feature_evidence')

            repo._stage_from_payload = fail_raw_stage_decode

            graph = BuildMoodAxisGraph(repo).execute('relaxing')

            self.assertEqual(tuple(node.track_id for node in graph.positioned), (first, second))
            self.assertEqual(tuple((edge.a, edge.b, edge.score) for edge in graph.edges), ((first, second, 0.75),))
            self.assertEqual(graph.selected_mood, 'relaxing')
            self.assertEqual(graph.available_moods, ('heavy', 'relaxing'))
            self.assertEqual(graph.metadata['graph_status']['state'], 'ready')
            self.assertEqual(graph.metadata['graph_status']['source'], 'graph_build_positioned_edges')

    def test_mixed_compact_and_legacy_tracks_match_verbose_graph_without_reading_compact_raw_stages(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'analysis.sqlite'
            writer = SQLiteAnalysisRepository(str(path))
            compact_a = add_positioned_track(writer, 'a')
            compact_b = add_positioned_track(writer, 'b', bpm=128.0, genres=(('rock', 'jazz'), (0.05, 0.8)))
            legacy = add_positioned_track(writer, 'c', bpm=96.0, mood=(('relaxing', 'heavy'), (0.1, 0.9)))
            writer.replace_graph_snapshot(
                (ProjectionEdge(compact_a, compact_b, 0.25, 2), ProjectionEdge(compact_a, legacy, 0.5, 1)),
                10,
                'synthetic-analyzer-mixed-red',
                positioned_edges=(ProjectionEdge(compact_a, compact_b, 0.25, 2), ProjectionEdge(compact_a, legacy, 0.5, 1)),
            )
            expected = BuildMoodAxisGraph(ReadOnlyExplorerSQLiteRepository(str(path))).execute('relaxing')

            with closing(sqlite3.connect(path)) as db, db:
                legacy_run = db.execute('SELECT run_id FROM run_tracks WHERE track_id=?', (legacy,)).fetchone()[0]
                db.execute('DELETE FROM graph_feature_evidence WHERE track_id=?', (legacy,))
                db.execute(
                    "UPDATE stages SET result='{}' WHERE run_id IN (SELECT run_id FROM run_tracks WHERE track_id IN (?,?))",
                    (compact_a, compact_b),
                )
                self.assertEqual(db.execute('SELECT count(*) FROM stages WHERE run_id=?', (legacy_run,)).fetchone()[0], 5)

            repo = ReadOnlyExplorerSQLiteRepository(str(path))
            original_stage_from_payload = repo._stage_from_payload

            def fail_only_if_compact_track_raw_stage_is_decoded(stage, size, payload):
                if payload == '{}':
                    raise AssertionError('compact evidence tracks must not fall back to raw stages.result decoding')
                return original_stage_from_payload(stage, size, payload)

            repo._stage_from_payload = fail_only_if_compact_track_raw_stage_is_decoded

            graph = BuildMoodAxisGraph(repo).execute('relaxing')

            self.assertEqual(graph.selected_mood, expected.selected_mood)
            self.assertEqual(graph.available_moods, expected.available_moods)
            self.assertEqual(tuple(node.track_id for node in graph.positioned), tuple(node.track_id for node in expected.positioned))
            self.assertEqual(
                tuple((node.track_id, node.x.raw, node.x.normalized, node.y.raw, node.y.normalized, node.z.raw, node.bpm, node.genres, node.reasons) for node in graph.positioned),
                tuple((node.track_id, node.x.raw, node.x.normalized, node.y.raw, node.y.normalized, node.z.raw, node.bpm, node.genres, node.reasons) for node in expected.positioned),
            )
            self.assertEqual(tuple((item.track_id, item.reasons) for item in graph.unpositioned), tuple((item.track_id, item.reasons) for item in expected.unpositioned))
            self.assertEqual(tuple((edge.a, edge.b, edge.score, edge.supported_group_count) for edge in graph.edges), tuple((edge.a, edge.b, edge.score, edge.supported_group_count) for edge in expected.edges))
            self.assertEqual(graph.metadata['graph_status'], expected.metadata['graph_status'])


if __name__ == '__main__':
    unittest.main()
