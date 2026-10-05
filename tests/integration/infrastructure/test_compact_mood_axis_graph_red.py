import re
import sqlite3
import tempfile
import unittest
from contextlib import closing, contextmanager
from pathlib import Path

from music_analyzer.application.dto.analysis import AudioSource, StageResult
from music_analyzer.application.dto.catalogue import Inventory, ScannedFile, TrackMetadata
from music_analyzer.application.use_cases.explorer import BuildMoodAxisGraph
from music_analyzer.domain.analysis import ScoreSummary
from music_analyzer.domain.catalogue import FileIdentity
from music_analyzer.domain.projection import ProjectionEdge
from music_analyzer.infrastructure.persistence.analysis import SQLiteAnalysisRepository
from music_analyzer.infrastructure.persistence.explorer_readonly import ReadOnlyExplorerSQLiteRepository
from music_explorer.application.use_cases.explorer import BuildMoodAxisGraph as StandaloneBuildMoodAxisGraph
from music_explorer.infrastructure.explorer_readonly import AnalysisError as StandaloneAnalysisError
from music_explorer.infrastructure.explorer_readonly import ReadOnlyExplorerSQLiteRepository as StandaloneReadOnlyExplorerSQLiteRepository


def summary(labels, values, provisional=True):
    return ScoreSummary(tuple(labels), tuple(values), tuple(values), tuple(values), 1.0, provisional, '')


def trace_graph_sql(repo, execute_graph):
    statements = []
    original_connection = repo._connection

    @contextmanager
    def traced_connection():
        with original_connection() as db:
            db.set_trace_callback(statements.append)
            yield db

    repo._connection = traced_connection
    try:
        graph = execute_graph(repo)
    finally:
        repo._connection = original_connection
    return graph, tuple(statements)


def raw_stage_result_selects(statements):
    selects = []
    for statement in statements:
        normalized = ' '.join(statement.split()).upper()
        if ' STAGES' not in normalized:
            continue
        match = re.search(r'\bSELECT\b(?P<select>.*?)\bFROM\b', normalized)
        if match is None:
            continue
        select_list = re.sub(r'\b(?:OCTET_LENGTH|LENGTH)\s*\([^)]*\bRESULT\b[^)]*\)', '', match.group('select'))
        if re.search(r'\b(?:[A-Z_][A-Z0-9_]*\.)?RESULT\b', select_list):
            selects.append(statement)
    return tuple(selects)


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


class CompactMoodAxisGraphReadTests(unittest.TestCase):
    def test_standalone_mood_axis_graph_uses_compact_evidence_without_decoding_raw_stages(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'analysis.sqlite'
            writer = SQLiteAnalysisRepository(str(path))
            first = add_positioned_track(writer, 'a')
            second = add_positioned_track(writer, 'b', bpm=128.0, genres=(('rock', 'jazz'), (0.05, 0.8)))
            writer.replace_graph_snapshot(
                (ProjectionEdge(first, second, 0.25, 2),),
                10,
                'synthetic-standalone-compact-red',
                positioned_edges=(ProjectionEdge(first, second, 0.25, 2),),
            )
            with closing(sqlite3.connect(path)) as db:
                self.assertEqual(
                    2,
                    db.execute('SELECT count(*) FROM graph_feature_evidence WHERE is_current=1').fetchone()[0],
                )
            repo = StandaloneReadOnlyExplorerSQLiteRepository(str(path))

            def fail_raw_stage_decode(*args, **kwargs):
                raise AssertionError('_stage_from_payload should not be called for tracks with current compact graph_feature_evidence')

            repo._stage_from_payload = fail_raw_stage_decode

            graph = StandaloneBuildMoodAxisGraph(repo).execute('relaxing')

            self.assertEqual(tuple(node.track_id for node in graph.positioned), (first, second))
            self.assertEqual(tuple((edge.a, edge.b, edge.score) for edge in graph.edges), ((first, second, 0.75),))
            self.assertEqual(graph.selected_mood, 'relaxing')
            self.assertEqual(graph.available_moods, ('heavy', 'relaxing'))
            self.assertEqual(graph.metadata['graph_status']['state'], 'ready')
            self.assertEqual(graph.metadata['graph_status']['source'], 'graph_build_positioned_edges')

    def test_standalone_mixed_compact_and_legacy_tracks_read_raw_stages_only_for_legacy_fallback(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'analysis.sqlite'
            writer = SQLiteAnalysisRepository(str(path))
            compact_a = add_positioned_track(writer, 'a')
            compact_b = add_positioned_track(writer, 'b', bpm=128.0, genres=(('rock', 'jazz'), (0.05, 0.8)))
            legacy = add_positioned_track(writer, 'c', bpm=96.0, mood=(('relaxing', 'heavy'), (0.1, 0.9)))
            writer.replace_graph_snapshot(
                (ProjectionEdge(compact_a, compact_b, 0.25, 2), ProjectionEdge(compact_a, legacy, 0.5, 1)),
                10,
                'synthetic-standalone-mixed-red',
                positioned_edges=(ProjectionEdge(compact_a, compact_b, 0.25, 2), ProjectionEdge(compact_a, legacy, 0.5, 1)),
            )
            expected = StandaloneBuildMoodAxisGraph(StandaloneReadOnlyExplorerSQLiteRepository(str(path))).execute('relaxing')

            with closing(sqlite3.connect(path)) as db, db:
                legacy_run = db.execute('SELECT run_id FROM run_tracks WHERE track_id=?', (legacy,)).fetchone()[0]
                db.execute('DELETE FROM graph_feature_evidence WHERE track_id=?', (legacy,))
                db.execute(
                    "UPDATE stages SET result='{}' WHERE run_id IN (SELECT run_id FROM run_tracks WHERE track_id IN (?,?))",
                    (compact_a, compact_b),
                )
                self.assertEqual(db.execute('SELECT count(*) FROM stages WHERE run_id=?', (legacy_run,)).fetchone()[0], 5)

            repo = StandaloneReadOnlyExplorerSQLiteRepository(str(path))
            original_stage_from_payload = repo._stage_from_payload

            def fail_only_if_compact_track_raw_stage_is_decoded(stage, size, payload):
                if payload == '{}':
                    raise AssertionError('compact evidence tracks must not fall back to raw stages.result decoding')
                return original_stage_from_payload(stage, size, payload)

            repo._stage_from_payload = fail_only_if_compact_track_raw_stage_is_decoded

            graph = StandaloneBuildMoodAxisGraph(repo).execute('relaxing')

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

    def test_standalone_all_compact_snapshot_does_not_select_raw_stage_result_sql(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'analysis.sqlite'
            writer = SQLiteAnalysisRepository(str(path))
            first = add_positioned_track(writer, 'a')
            second = add_positioned_track(writer, 'b', bpm=128.0, genres=(('rock', 'jazz'), (0.05, 0.8)))
            writer.replace_graph_snapshot(
                (ProjectionEdge(first, second, 0.25, 2),),
                10,
                'synthetic-standalone-sql-trace-red',
                positioned_edges=(ProjectionEdge(first, second, 0.25, 2),),
            )

            graph, statements = trace_graph_sql(
                StandaloneReadOnlyExplorerSQLiteRepository(str(path)),
                lambda repo: StandaloneBuildMoodAxisGraph(repo).execute('relaxing'),
            )

            self.assertEqual(tuple(node.track_id for node in graph.positioned), (first, second))
            self.assertEqual(
                (),
                raw_stage_result_selects(statements),
                'all-compact graph reads must not execute SQL that selects raw stages.result payloads; '
                'size-only octet_length(s.result) probes are the only permitted stages.result reference',
            )

    def test_standalone_mixed_snapshot_selects_raw_stage_result_sql_only_for_legacy_run(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'analysis.sqlite'
            writer = SQLiteAnalysisRepository(str(path))
            compact_a = add_positioned_track(writer, 'a')
            compact_b = add_positioned_track(writer, 'b', bpm=128.0, genres=(('rock', 'jazz'), (0.05, 0.8)))
            legacy = add_positioned_track(writer, 'c', bpm=96.0, mood=(('relaxing', 'heavy'), (0.1, 0.9)))
            writer.replace_graph_snapshot(
                (ProjectionEdge(compact_a, compact_b, 0.25, 2), ProjectionEdge(compact_a, legacy, 0.5, 1)),
                10,
                'synthetic-standalone-mixed-sql-trace-red',
                positioned_edges=(ProjectionEdge(compact_a, compact_b, 0.25, 2), ProjectionEdge(compact_a, legacy, 0.5, 1)),
            )
            with closing(sqlite3.connect(path)) as db, db:
                compact_runs = tuple(
                    row[0] for row in db.execute(
                        'SELECT run_id FROM run_tracks WHERE track_id IN (?,?) ORDER BY track_id',
                        (compact_a, compact_b),
                    )
                )
                legacy_run = db.execute('SELECT run_id FROM run_tracks WHERE track_id=?', (legacy,)).fetchone()[0]
                db.execute('DELETE FROM graph_feature_evidence WHERE track_id=?', (legacy,))

            graph, statements = trace_graph_sql(
                StandaloneReadOnlyExplorerSQLiteRepository(str(path)),
                lambda repo: StandaloneBuildMoodAxisGraph(repo).execute('relaxing'),
            )
            raw_selects = raw_stage_result_selects(statements)

            self.assertEqual(tuple(node.track_id for node in graph.positioned), (compact_a, compact_b, legacy))
            self.assertTrue(raw_selects, 'legacy fallback must perform bounded raw stage payload reads for the legacy track')
            self.assertTrue(
                all(legacy_run in statement for statement in raw_selects),
                f'raw stage payload SELECTs must be bounded to legacy run {legacy_run}; got {raw_selects!r}',
            )
            self.assertFalse(
                any(compact_run in statement for compact_run in compact_runs for statement in raw_selects),
                f'compact run raw payloads must never be selected; compact_runs={compact_runs!r}, selects={raw_selects!r}',
            )

    def test_standalone_malformed_current_compact_evidence_fails_closed_without_raw_fallback(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'analysis.sqlite'
            writer = SQLiteAnalysisRepository(str(path))
            first = add_positioned_track(writer, 'a')
            second = add_positioned_track(writer, 'b', bpm=128.0, genres=(('rock', 'jazz'), (0.05, 0.8)))
            writer.replace_graph_snapshot(
                (ProjectionEdge(first, second, 0.25, 2),),
                10,
                'synthetic-standalone-malformed-evidence-red',
                positioned_edges=(ProjectionEdge(first, second, 0.25, 2),),
            )
            with closing(sqlite3.connect(path)) as db, db:
                db.execute(
                    "UPDATE graph_feature_evidence SET fingerprint=? WHERE track_id=? AND is_current=1",
                    ('not-a-valid-fingerprint', first),
                )

            with self.assertRaises(StandaloneAnalysisError):
                StandaloneBuildMoodAxisGraph(StandaloneReadOnlyExplorerSQLiteRepository(str(path))).execute('relaxing')

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
