import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from music_analyzer.application.dto.analysis import AnalysisError, AudioSource, StageResult
from music_analyzer.application.dto.catalogue import Inventory, ScannedFile, TrackMetadata
from music_analyzer.domain.catalogue import FileIdentity
from music_analyzer.domain.projection import ProjectionEdge
from music_analyzer.infrastructure.persistence.analysis import APPLICATION_ID, SQLiteAnalysisRepository
from music_analyzer.infrastructure.persistence.explorer_readonly import ReadOnlyExplorerSQLiteRepository


def create_v6_database(path: Path) -> None:
    with closing(sqlite3.connect(path)) as db, db:
        db.executescript('''
            CREATE TABLE runs (id TEXT PRIMARY KEY, location TEXT NOT NULL, status TEXT NOT NULL CHECK(status IN ('running','completed','failed','interrupted')), detail TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
            CREATE TABLE stages (run_id TEXT NOT NULL REFERENCES runs(id), stage TEXT NOT NULL, result TEXT NOT NULL, PRIMARY KEY(run_id,stage));
            CREATE TABLE tracks(id TEXT PRIMARY KEY, sha256 TEXT NOT NULL UNIQUE, size INTEGER NOT NULL);
            CREATE TABLE locations(path TEXT PRIMARY KEY, track_id TEXT NOT NULL REFERENCES tracks(id), mtime_ns INTEGER NOT NULL, format TEXT NOT NULL, available INTEGER NOT NULL CHECK(available IN (0,1)));
            CREATE TABLE scan_roots(root TEXT NOT NULL, path TEXT NOT NULL REFERENCES locations(path), PRIMARY KEY(root,path));
            CREATE TABLE batch_jobs(track_id TEXT PRIMARY KEY REFERENCES tracks(id), fingerprint TEXT NOT NULL, state TEXT NOT NULL CHECK(state IN ('pending','running','completed','failed')), attempts INTEGER NOT NULL CHECK(attempts >= 0), run_id TEXT, detail TEXT NOT NULL);
            CREATE TABLE run_tracks(run_id TEXT PRIMARY KEY REFERENCES runs(id), track_id TEXT NOT NULL REFERENCES tracks(id));
            CREATE TABLE overrides(track_id TEXT NOT NULL REFERENCES tracks(id), field TEXT NOT NULL, value TEXT NOT NULL, PRIMARY KEY(track_id,field));
            CREATE TABLE track_metadata(track_id TEXT PRIMARY KEY REFERENCES tracks(id), common_json TEXT NOT NULL, tags_json TEXT NOT NULL, warnings_json TEXT NOT NULL);
            CREATE TABLE track_audio(track_id TEXT PRIMARY KEY REFERENCES tracks(id), duration_seconds REAL, duration_source TEXT NOT NULL, status TEXT NOT NULL CHECK(status IN ('eligible','excluded','unknown')), reason TEXT NOT NULL);
            CREATE VIEW active_tracks AS SELECT t.id,t.sha256,t.size FROM tracks t JOIN track_audio a ON a.track_id=t.id WHERE a.status='eligible';
            CREATE VIEW active_locations AS SELECT l.path,l.track_id,l.mtime_ns,l.format,l.available FROM locations l JOIN track_audio a ON a.track_id=l.track_id WHERE l.available=1 AND a.status='eligible';
        ''')
        db.execute(f'PRAGMA application_id={APPLICATION_ID}')
        db.execute('PRAGMA user_version=6')
        track_id = 'sha256:' + 'a' * 64
        db.execute('INSERT INTO tracks VALUES(?,?,?)', (track_id, 'a' * 64, 123))
        db.execute('INSERT INTO locations VALUES(?,?,?,?,?)', ('/music/Retained.flac', track_id, 7, 'flac', 1))
        db.execute('INSERT INTO scan_roots VALUES(?,?)', ('/music', '/music/Retained.flac'))
        db.execute('INSERT INTO runs VALUES(?,?,?,?,?)', ('run-a', '/music/Retained.flac', 'completed', 'ok', 'then'))
        db.execute('INSERT INTO run_tracks VALUES(?,?)', ('run-a', track_id))
        db.execute('INSERT INTO stages VALUES(?,?,?)', ('run-a', 'bpm', json.dumps({
            'stage': 'bpm', 'provenance': [['fixture', 'retained']], 'uncertainty': '', 'values': [['bpm', 120.0]],
        })))
        db.execute('INSERT INTO overrides VALUES(?,?,?)', (track_id, 'key', 'C'))
        db.execute('INSERT INTO batch_jobs VALUES(?,?,?,?,?,?)', (track_id, 'fingerprint-v6', 'completed', 1, 'run-a', 'keep'))
        db.execute('INSERT INTO track_metadata VALUES(?,?,?,?)', (track_id, '[["title","Retained"]]', '[]', '[]'))
        db.execute('INSERT INTO track_audio VALUES(?,?,?,?,?)', (track_id, 180.0, 'mutagen', 'eligible', ''))


class GraphBuildSchemaMigrationTests(unittest.TestCase):
    def test_v6_database_migrates_to_v9_with_graph_edge_schema_without_losing_history(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'analysis.sqlite'
            create_v6_database(path)

            SQLiteAnalysisRepository(str(path))

            with closing(sqlite3.connect(path)) as db:
                self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0], 9)
                self.assertEqual(
                    db.execute('SELECT id,sha256,size FROM tracks').fetchone(),
                    ('sha256:' + 'a' * 64, 'a' * 64, 123),
                )
                self.assertEqual(db.execute('SELECT status,detail FROM runs WHERE id=?', ('run-a',)).fetchone(), ('completed', 'ok'))
                self.assertEqual(db.execute('SELECT stage FROM stages WHERE run_id=?', ('run-a',)).fetchone(), ('bpm',))
                self.assertEqual(db.execute('SELECT field,value FROM overrides').fetchone(), ('key', 'C'))
                self.assertEqual(db.execute('SELECT state,run_id,detail FROM batch_jobs').fetchone(), ('completed', 'run-a', 'keep'))
                self.assertEqual(db.execute('SELECT status,reason FROM track_audio').fetchone(), ('eligible', ''))

                build_columns = tuple(row[1] for row in db.execute('PRAGMA table_info(graph_builds)'))
                self.assertEqual(
                    build_columns,
                    ('id', 'status', 'detail', 'edge_count', 'sparse_k', 'source_fingerprint', 'distance_policy_version', 'neighbour_policy_version', 'is_current', 'created_at', 'completed_at'),
                )
                build_sql = ' '.join(db.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='graph_builds'").fetchone()[0].split())
                self.assertIn('CHECK(is_current IN (0,1))', build_sql)
                self.assertIn("CHECK(status = 'completed' OR is_current = 0)", build_sql)

                graph_columns = tuple(row[1] for row in db.execute('PRAGMA table_info(graph_edges)'))
                self.assertEqual(
                    graph_columns,
                    ('source_track_id', 'target_track_id', 'score', 'distance', 'supported_group_count', 'distance_policy_version', 'neighbour_policy_version', 'built_at'),
                )
                graph_sql = ' '.join(db.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='graph_edges'").fetchone()[0].split())
                self.assertIn('PRIMARY KEY(source_track_id,target_track_id)', graph_sql)
                self.assertIn('CHECK(source_track_id < target_track_id)', graph_sql)
                self.assertIn('CHECK(score >= 0.0 AND score <= 1.0)', graph_sql)
                self.assertIn('CHECK(distance >= 0.0 AND distance <= 1.0)', graph_sql)
                foreign_keys = tuple((row[3], row[2], row[4]) for row in db.execute('PRAGMA foreign_key_list(graph_edges)'))
                self.assertIn(('source_track_id', 'tracks', 'id'), foreign_keys)
                self.assertIn(('target_track_id', 'tracks', 'id'), foreign_keys)
                indexes = {row[1] for row in db.execute('PRAGMA index_list(graph_edges)')}
                self.assertIn('idx_graph_edges_source_track_id', indexes)
                self.assertIn('idx_graph_edges_target_track_id', indexes)

                build_edge_columns = tuple(row[1] for row in db.execute('PRAGMA table_info(graph_build_edges)'))
                self.assertEqual(build_edge_columns, ('build_id', 'source_track_id', 'target_track_id', 'score', 'distance', 'supported_group_count', 'distance_policy_version', 'neighbour_policy_version', 'built_at'))
                build_edge_sql = ' '.join(db.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='graph_build_edges'").fetchone()[0].split())
                self.assertIn('PRIMARY KEY(build_id,source_track_id,target_track_id)', build_edge_sql)
                build_edge_foreign_keys = tuple((row[3], row[2], row[4]) for row in db.execute('PRAGMA foreign_key_list(graph_build_edges)'))
                self.assertIn(('build_id', 'graph_builds', 'id'), build_edge_foreign_keys)
                build_edge_indexes = {row[1] for row in db.execute('PRAGMA index_list(graph_build_edges)')}
                self.assertIn('idx_graph_build_edges_build_id', build_edge_indexes)
                self.assertIn('idx_graph_build_edges_source_track_id', build_edge_indexes)
                self.assertIn('idx_graph_build_edges_target_track_id', build_edge_indexes)
                build_indexes = {row[1] for row in db.execute('PRAGMA index_list(graph_builds)')}
                self.assertIn('idx_graph_builds_one_current', build_indexes)

    def test_repeated_graph_builds_keep_versioned_edges_and_single_current_pointer(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'analysis.sqlite'
            create_v6_database(path)
            repository = SQLiteAnalysisRepository(str(path))
            with closing(sqlite3.connect(path)) as db, db:
                for suffix in ('b', 'c'):
                    track_id = 'sha256:' + suffix * 64
                    db.execute('INSERT INTO tracks VALUES(?,?,?)', (track_id, suffix * 64, 123))
                    db.execute('INSERT INTO track_audio VALUES(?,?,?,?,?)', (track_id, 180.0, 'mutagen', 'eligible', ''))

            first_id = repository.replace_graph_snapshot((
                ProjectionEdge('sha256:' + 'a' * 64, 'sha256:' + 'b' * 64, 0.25, 2),
            ), 10, 'fingerprint-one')
            second_id = repository.replace_graph_snapshot((
                ProjectionEdge('sha256:' + 'a' * 64, 'sha256:' + 'c' * 64, 0.5, 2),
                ProjectionEdge('sha256:' + 'b' * 64, 'sha256:' + 'c' * 64, 0.75, 2),
            ), 10, 'fingerprint-two')
            failed_id = repository.record_graph_failure(10, 'fingerprint-three', 'synthetic failure')

            with closing(sqlite3.connect(path)) as db:
                self.assertEqual(
                    tuple(db.execute('SELECT id,status,edge_count,is_current,source_fingerprint FROM graph_builds ORDER BY rowid')),
                    (
                        (first_id, 'completed', 1, 0, 'fingerprint-one'),
                        (second_id, 'completed', 2, 1, 'fingerprint-two'),
                        (failed_id, 'failed', 0, 0, 'fingerprint-three'),
                    ),
                )
                self.assertEqual(
                    tuple(db.execute('SELECT source_track_id,target_track_id FROM graph_build_edges WHERE build_id=?', (first_id,))),
                    (('sha256:' + 'a' * 64, 'sha256:' + 'b' * 64),),
                )
                self.assertEqual(
                    tuple(db.execute('SELECT source_track_id,target_track_id FROM graph_build_edges WHERE build_id=? ORDER BY source_track_id,target_track_id', (second_id,))),
                    (
                        ('sha256:' + 'a' * 64, 'sha256:' + 'c' * 64),
                        ('sha256:' + 'b' * 64, 'sha256:' + 'c' * 64),
                    ),
                )
                self.assertEqual(db.execute('SELECT count(*) FROM graph_build_edges WHERE build_id=?', (failed_id,)).fetchone()[0], 0)

            # The read-only mirror accepts the strict versioned schema and row invariants.
            self.assertEqual(ReadOnlyExplorerSQLiteRepository(str(path)).metadata()['schema_version'], 9)

    def test_failed_replacement_rolls_back_new_build_and_leaves_previous_current_snapshot_intact(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'analysis.sqlite'
            create_v6_database(path)
            repository = SQLiteAnalysisRepository(str(path))
            with closing(sqlite3.connect(path)) as db, db:
                track_id = 'sha256:' + 'b' * 64
                db.execute('INSERT INTO tracks VALUES(?,?,?)', (track_id, 'b' * 64, 123))
                db.execute('INSERT INTO track_audio VALUES(?,?,?,?,?)', (track_id, 180.0, 'mutagen', 'eligible', ''))

            current_id = repository.replace_graph_snapshot((
                ProjectionEdge('sha256:' + 'a' * 64, 'sha256:' + 'b' * 64, 0.25, 2),
            ), 10, 'fingerprint-one')
            with self.assertRaises(AnalysisError):
                repository.replace_graph_snapshot((
                    ProjectionEdge('sha256:' + 'a' * 64, 'sha256:' + 'b' * 64, 0.25, 2),
                    ProjectionEdge('sha256:' + 'a' * 64, 'sha256:' + 'c' * 64, 0.50, 2),
                ), 10, 'fingerprint-bad')

            with closing(sqlite3.connect(path)) as db:
                self.assertEqual(
                    tuple(db.execute('SELECT id,status,edge_count,is_current,source_fingerprint FROM graph_builds')),
                    ((current_id, 'completed', 1, 1, 'fingerprint-one'),),
                )
                self.assertEqual(db.execute('SELECT source_track_id,target_track_id FROM graph_edges').fetchone(), ('sha256:' + 'a' * 64, 'sha256:' + 'b' * 64))
                self.assertEqual(db.execute('SELECT build_id FROM graph_build_edges').fetchone(), (current_id,))

    def test_graph_relevant_writers_invalidate_current_snapshot_including_reanalysis_start(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'analysis.sqlite'
            create_v6_database(path)
            repository = SQLiteAnalysisRepository(str(path))
            with closing(sqlite3.connect(path)) as db, db:
                track_id = 'sha256:' + 'b' * 64
                db.execute('INSERT INTO tracks VALUES(?,?,?)', (track_id, 'b' * 64, 123))
                db.execute('INSERT INTO track_audio VALUES(?,?,?,?,?)', (track_id, 180.0, 'mutagen', 'eligible', ''))
            repository.replace_graph_snapshot((
                ProjectionEdge('sha256:' + 'a' * 64, 'sha256:' + 'b' * 64, 0.25, 2),
            ), 10, 'fingerprint-one')
            failed = repository.start(AudioSource('/music/Retained.flac', 'sha256:' + 'a' * 64))
            repository.finish(failed, 'failed', 'no graph-relevant completed output')
            with closing(sqlite3.connect(path)) as db:
                self.assertEqual(db.execute('SELECT count(*) FROM graph_builds WHERE is_current=1').fetchone()[0], 0)
                self.assertEqual(db.execute('SELECT count(*) FROM graph_edges').fetchone()[0], 0)
            repository.replace_graph_snapshot((
                ProjectionEdge('sha256:' + 'a' * 64, 'sha256:' + 'b' * 64, 0.25, 2),
            ), 10, 'fingerprint-two')
            run = repository.start(AudioSource('/music/Retained.flac', 'sha256:' + 'a' * 64))
            repository.save_stage(run, StageResult('bpm', (('algorithm', 'test'),), '', (('bpm', 121.0),)))
            repository.finish(run, 'completed', '')
            with closing(sqlite3.connect(path)) as db:
                self.assertEqual(db.execute('SELECT count(*) FROM graph_builds WHERE is_current=1').fetchone()[0], 0)
            repository.replace_graph_snapshot((
                ProjectionEdge('sha256:' + 'a' * 64, 'sha256:' + 'b' * 64, 0.25, 2),
            ), 10, 'fingerprint-three')
            repository.set_override('sha256:' + 'a' * 64, 'bpm', '122')
            with closing(sqlite3.connect(path)) as db:
                self.assertEqual(db.execute('SELECT count(*) FROM graph_builds WHERE is_current=1').fetchone()[0], 0)
            repository.replace_graph_snapshot((
                ProjectionEdge('sha256:' + 'a' * 64, 'sha256:' + 'b' * 64, 0.25, 2),
            ), 10, 'fingerprint-four')
            identity = FileIdentity('a' * 64, 123)
            repository.register(Inventory('/music', (
                ScannedFile('/music/Retained.flac', identity, 8, 'flac', TrackMetadata(duration_seconds=180.0, duration_source='mutagen')),
            ), (), True))
            with closing(sqlite3.connect(path)) as db:
                self.assertEqual(db.execute('SELECT count(*) FROM graph_builds WHERE is_current=1').fetchone()[0], 0)

    def test_read_only_validator_rejects_completed_history_without_single_current_build(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'analysis.sqlite'
            create_v6_database(path)
            repository = SQLiteAnalysisRepository(str(path))
            with closing(sqlite3.connect(path)) as db, db:
                track_id = 'sha256:' + 'b' * 64
                db.execute('INSERT INTO tracks VALUES(?,?,?)', (track_id, 'b' * 64, 123))
                db.execute('INSERT INTO track_audio VALUES(?,?,?,?,?)', (track_id, 180.0, 'mutagen', 'eligible', ''))
            repository.replace_graph_snapshot((
                ProjectionEdge('sha256:' + 'a' * 64, 'sha256:' + 'b' * 64, 0.25, 2),
            ), 10, 'fingerprint-one')
            with closing(sqlite3.connect(path)) as db, db:
                db.execute('UPDATE graph_builds SET is_current=0')

            with self.assertRaises(AnalysisError):
                ReadOnlyExplorerSQLiteRepository(str(path)).metadata()


if __name__ == '__main__':
    unittest.main()
