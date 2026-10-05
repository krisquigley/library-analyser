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


def downgrade_to_schema_v8_without_graph_feature_evidence(path):
    with closing(sqlite3.connect(path)) as db, db:
        db.execute('PRAGMA foreign_keys=OFF')
        db.execute('PRAGMA legacy_alter_table=ON')
        db.execute('DROP INDEX IF EXISTS idx_graph_feature_evidence_one_current_per_track')
        db.execute('DROP INDEX IF EXISTS idx_graph_feature_evidence_run_id')
        db.execute('DROP TABLE graph_feature_evidence')
        db.execute('ALTER TABLE graph_builds RENAME TO graph_builds_v10')
        db.execute("""CREATE TABLE graph_builds(
            id TEXT PRIMARY KEY,
            status TEXT NOT NULL CHECK(status IN ('completed','failed')),
            detail TEXT NOT NULL DEFAULT '',
            edge_count INTEGER NOT NULL CHECK(edge_count >= 0),
            sparse_k INTEGER NOT NULL CHECK(sparse_k >= 0),
            source_fingerprint TEXT NOT NULL,
            distance_policy_version TEXT NOT NULL,
            neighbour_policy_version TEXT NOT NULL,
            is_current INTEGER NOT NULL DEFAULT 0 CHECK(is_current IN (0,1)),
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            completed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            CHECK(status = 'completed' OR is_current = 0))""")
        db.execute("""INSERT INTO graph_builds(
            id,status,detail,edge_count,sparse_k,source_fingerprint,
            distance_policy_version,neighbour_policy_version,is_current,created_at,completed_at)
            SELECT id,status,detail,edge_count,sparse_k,source_fingerprint,
                   distance_policy_version,neighbour_policy_version,is_current,created_at,completed_at
            FROM graph_builds_v10""")
        db.execute('DROP TABLE graph_builds_v10')
        db.execute("""CREATE UNIQUE INDEX idx_graph_builds_one_current
                   ON graph_builds(is_current) WHERE is_current = 1""")
        db.execute('PRAGMA user_version=8')
        db.execute('PRAGMA legacy_alter_table=OFF')
        db.execute('PRAGMA foreign_keys=ON')
        assert db.execute("SELECT 1 FROM sqlite_master WHERE name='graph_feature_evidence'").fetchone() is None


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
    return add_positioned_track_identity(repository, identity, location, bpm=bpm, genres=genres, mood=mood)


def add_positioned_track_identity(repository, identity, location, *, bpm=120.0, genres=(('rock', 'jazz'), (0.9, 0.1)), mood=(('relaxing', 'heavy'), (0.8, 0.2))):
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

    def test_standalone_supported_v8_warm_positioned_snapshot_uses_raw_stage_fallback_without_graph_feature_evidence(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'analysis.sqlite'
            writer = SQLiteAnalysisRepository(str(path))
            first = add_positioned_track(writer, 'a')
            second = add_positioned_track(writer, 'b', bpm=128.0, genres=(('rock', 'jazz'), (0.05, 0.8)))
            writer.replace_graph_snapshot(
                (ProjectionEdge(first, second, 0.25, 2),),
                10,
                'synthetic-standalone-v8-red',
                positioned_edges=(ProjectionEdge(first, second, 0.25, 2),),
            )
            downgrade_to_schema_v8_without_graph_feature_evidence(path)

            graph = StandaloneBuildMoodAxisGraph(StandaloneReadOnlyExplorerSQLiteRepository(str(path))).execute('relaxing')

            self.assertEqual(tuple(node.track_id for node in graph.positioned), (first, second))
            self.assertEqual(tuple((edge.a, edge.b, edge.score) for edge in graph.edges), ((first, second, 0.75),))
            self.assertEqual(graph.metadata['schema_version'], 8)
            self.assertEqual(graph.metadata['graph_status']['state'], 'ready')
            self.assertEqual(graph.metadata['graph_status']['source'], 'graph_build_positioned_edges')

    def test_standalone_oversized_current_compact_evidence_fails_before_json_materialization(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'analysis.sqlite'
            writer = SQLiteAnalysisRepository(str(path))
            first = add_positioned_track(writer, 'a')
            second = add_positioned_track(writer, 'b', bpm=128.0, genres=(('rock', 'jazz'), (0.05, 0.8)))
            writer.replace_graph_snapshot(
                (ProjectionEdge(first, second, 0.25, 2),),
                10,
                'synthetic-standalone-oversized-evidence-red',
                positioned_edges=(ProjectionEdge(first, second, 0.25, 2),),
            )
            oversized = '{"pad":"' + ('€' * ((16 * 1024 * 1024) // len('€'.encode('utf-8')) + 1)) + '"}'
            self.assertGreater(len(oversized.encode('utf-8')), 16 * 1024 * 1024)
            with closing(sqlite3.connect(path)) as db, db:
                db.execute(
                    'UPDATE graph_feature_evidence SET evidence_json=?, fingerprint=? WHERE track_id=? AND is_current=1',
                    (oversized, '0' * 64, first),
                )

            with self.assertRaisesRegex(StandaloneAnalysisError, 'Oversized stored graph feature evidence'):
                StandaloneBuildMoodAxisGraph(StandaloneReadOnlyExplorerSQLiteRepository(str(path))).execute('relaxing')

    def test_standalone_1000_plus_legacy_runs_do_not_exceed_old_sqlite_variable_limit(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'analysis.sqlite'
            writer = SQLiteAnalysisRepository(str(path))
            first = add_positioned_track(writer, 'a')
            writer.replace_graph_snapshot((), 10, 'synthetic-standalone-legacy-limit-red', positioned_edges=())
            with closing(sqlite3.connect(path)) as db, db:
                source_run = db.execute('SELECT run_id FROM run_tracks WHERE track_id=?', (first,)).fetchone()[0]
                source_stages = tuple(db.execute('SELECT stage,result FROM stages WHERE run_id=?', (source_run,)))
                for index in range(1, 1001):
                    sha = f'{index:064x}'
                    track_id = f'sha256:{sha}'
                    run_id = f'legacy-run-{index:04d}'
                    db.execute('INSERT INTO tracks VALUES(?,?,?)', (track_id, sha, 10))
                    db.execute('INSERT INTO locations VALUES(?,?,?,?,1)', (f'/music/{sha}.flac', track_id, 1, 'flac'))
                    db.execute('INSERT INTO scan_roots VALUES(?,?)', ('/music', f'/music/{sha}.flac'))
                    db.execute('INSERT INTO track_metadata VALUES(?,?,?,?)', (track_id, '[]', '[]', '[]'))
                    db.execute('INSERT INTO track_audio VALUES(?,?,?,?,?)', (track_id, 120.0, 'mutagen', 'eligible', ''))
                    db.execute('INSERT INTO runs(id,location,status,detail) VALUES(?,?,?,?)', (run_id, f'/music/{sha}.flac', 'completed', ''))
                    db.execute('INSERT INTO run_tracks VALUES(?,?)', (run_id, track_id))
                    db.executemany('INSERT INTO stages VALUES(?,?,?)', ((run_id, stage, result) for stage, result in source_stages))
                db.execute('DELETE FROM graph_feature_evidence')
                prior_limit = db.setlimit(sqlite3.SQLITE_LIMIT_VARIABLE_NUMBER, 999)
                self.assertGreaterEqual(prior_limit, 999)
            repo = StandaloneReadOnlyExplorerSQLiteRepository(str(path))
            original_connection = repo._connection

            @contextmanager
            def limited_connection():
                with original_connection() as db:
                    db.setlimit(sqlite3.SQLITE_LIMIT_VARIABLE_NUMBER, 999)
                    yield db

            repo._connection = limited_connection
            try:
                graph = StandaloneBuildMoodAxisGraph(repo).execute('relaxing')
            finally:
                repo._connection = original_connection

            self.assertEqual(len(graph.positioned) + len(graph.unpositioned), 1001)

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
