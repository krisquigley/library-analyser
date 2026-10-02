import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from music_analyzer.infrastructure.persistence.analysis import APPLICATION_ID, SQLiteAnalysisRepository


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
    def test_v6_database_migrates_to_v7_with_graph_edge_schema_without_losing_history(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'analysis.sqlite'
            create_v6_database(path)

            SQLiteAnalysisRepository(str(path))

            with closing(sqlite3.connect(path)) as db:
                self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0], 7)
                self.assertEqual(
                    db.execute('SELECT id,sha256,size FROM tracks').fetchone(),
                    ('sha256:' + 'a' * 64, 'a' * 64, 123),
                )
                self.assertEqual(db.execute('SELECT status,detail FROM runs WHERE id=?', ('run-a',)).fetchone(), ('completed', 'ok'))
                self.assertEqual(db.execute('SELECT stage FROM stages WHERE run_id=?', ('run-a',)).fetchone(), ('bpm',))
                self.assertEqual(db.execute('SELECT field,value FROM overrides').fetchone(), ('key', 'C'))
                self.assertEqual(db.execute('SELECT state,run_id,detail FROM batch_jobs').fetchone(), ('completed', 'run-a', 'keep'))
                self.assertEqual(db.execute('SELECT status,reason FROM track_audio').fetchone(), ('eligible', ''))

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


if __name__ == '__main__':
    unittest.main()
