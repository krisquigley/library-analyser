import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path

from music_analyzer.application.dto.analysis import AnalysisError
from music_analyzer.infrastructure.persistence.explorer_readonly import ReadOnlyExplorerSQLiteRepository

APP_ID = 0x4D414E41


def create_db(path):
    db = sqlite3.connect(path)
    db.executescript('''
    CREATE TABLE runs (id TEXT PRIMARY KEY, location TEXT NOT NULL, status TEXT NOT NULL CHECK(status IN ('running','completed','failed','interrupted')), detail TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
    CREATE TABLE stages (run_id TEXT NOT NULL REFERENCES runs(id), stage TEXT NOT NULL, result TEXT NOT NULL, PRIMARY KEY(run_id,stage));
    CREATE TABLE tracks(id TEXT PRIMARY KEY, sha256 TEXT NOT NULL UNIQUE, size INTEGER NOT NULL);
    CREATE TABLE locations(path TEXT PRIMARY KEY, track_id TEXT NOT NULL REFERENCES tracks(id), mtime_ns INTEGER NOT NULL, format TEXT NOT NULL, available INTEGER NOT NULL CHECK(available IN (0,1)));
    CREATE TABLE scan_roots(root TEXT NOT NULL, path TEXT NOT NULL REFERENCES locations(path), PRIMARY KEY(root,path));
    CREATE TABLE batch_jobs(track_id TEXT PRIMARY KEY REFERENCES tracks(id), fingerprint TEXT NOT NULL, state TEXT NOT NULL CHECK(state IN ('pending','running','completed','failed')), attempts INTEGER NOT NULL CHECK(attempts >= 0), run_id TEXT, detail TEXT NOT NULL);
    CREATE TABLE run_tracks(run_id TEXT PRIMARY KEY REFERENCES runs(id), track_id TEXT NOT NULL REFERENCES tracks(id));
    CREATE TABLE overrides(track_id TEXT NOT NULL REFERENCES tracks(id), field TEXT NOT NULL, value TEXT NOT NULL, PRIMARY KEY(track_id,field));
    ''')
    db.execute(f'PRAGMA application_id={APP_ID}')
    db.execute('PRAGMA user_version=4')
    return db


def stage(name, value=1.0):
    return json.dumps({'stage': name, 'provenance': [['fixture', 'unit']], 'uncertainty': '', 'values': [[name, value]]})


class ReadOnlyExplorerSQLiteRepositoryTests(unittest.TestCase):
    def test_rejects_empty_db_without_creating_schema(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'empty.sqlite'
            sqlite3.connect(path).close()
            with self.assertRaisesRegex(AnalysisError, 'supported music-analyzer'):
                ReadOnlyExplorerSQLiteRepository(str(path)).track_ids()
            self.assertEqual(sqlite3.connect(path).execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall(), [])

    def test_reads_latest_identity_linked_run_and_redacts_path_to_label(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'analysis.sqlite'
            db = create_db(path)
            tid = 'sha256:' + 'c' * 64
            db.execute('INSERT INTO tracks VALUES(?,?,?)', (tid, 'c' * 64, 10))
            db.execute('INSERT INTO locations VALUES(?,?,?,?,?)', ('/private/music/Artist/Track.flac', tid, 1, 'flac', 1))
            db.execute('INSERT INTO runs(id,location,status,detail) VALUES(?,?,?,?)', ('old', '/private/music/Artist/Track.flac', 'completed', 'old ok'))
            db.execute('INSERT INTO run_tracks VALUES(?,?)', ('old', tid))
            db.execute('INSERT INTO stages VALUES(?,?,?)', ('old', 'bpm', stage('bpm', 120.0)))
            db.execute('INSERT INTO runs(id,location,status,detail) VALUES(?,?,?,?)', ('new', '/private/music/Artist/Track.flac', 'failed', 'new failed'))
            db.execute('INSERT INTO run_tracks VALUES(?,?)', ('new', tid))
            db.execute('INSERT INTO overrides VALUES(?,?,?)', (tid, 'bpm', 'about 120 maybe'))
            db.commit(); db.close()
            repo = ReadOnlyExplorerSQLiteRepository(str(path))
            self.assertEqual(repo.track_ids(), (tid,))
            track = repo.read_track(tid)
            self.assertEqual(track.display_label, 'Track.flac')
            self.assertEqual(track.available_locations, 1)
            self.assertEqual(track.run.run_id, 'new')
            self.assertEqual(track.run.status, 'failed')
            self.assertEqual(track.run.stages, ())
            self.assertEqual(track.overrides, (('bpm', 'about 120 maybe'),))

    def test_query_only_and_read_only_leave_inventory_unchanged(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'analysis.sqlite'
            db = create_db(path)
            tid = 'sha256:' + 'd' * 64
            db.execute('INSERT INTO tracks VALUES(?,?,?)', (tid, 'd' * 64, 10))
            db.commit(); db.close()
            before = path.read_bytes()
            repo = ReadOnlyExplorerSQLiteRepository(str(path))
            self.assertEqual(repo.track_ids(), (tid,))
            self.assertEqual(path.read_bytes(), before)

    def test_wal_committed_rows_are_visible_to_readonly_adapter(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'analysis.sqlite'
            db = create_db(path)
            db.execute('PRAGMA journal_mode=WAL')
            tid = 'sha256:' + 'e' * 64
            db.execute('INSERT INTO tracks VALUES(?,?,?)', (tid, 'e' * 64, 10))
            db.commit()
            # Keep writer open so committed data remains represented through WAL sidecars.
            self.assertTrue(os.path.exists(str(path) + '-wal'))
            repo = ReadOnlyExplorerSQLiteRepository(str(path))
            self.assertIn(tid, repo.track_ids())
            db.close()

    def test_invalid_stage_payload_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'analysis.sqlite'
            db = create_db(path)
            tid = 'sha256:' + 'f' * 64
            db.execute('INSERT INTO tracks VALUES(?,?,?)', (tid, 'f' * 64, 10))
            db.execute('INSERT INTO runs(id,location,status,detail) VALUES(?,?,?,?)', ('run', '', 'completed', ''))
            db.execute('INSERT INTO run_tracks VALUES(?,?)', ('run', tid))
            db.execute('INSERT INTO stages VALUES(?,?,?)', ('run', 'bpm', '{"stage":"other","provenance":[],"uncertainty":""}'))
            db.commit(); db.close()
            with self.assertRaisesRegex(AnalysisError, 'Invalid stored stage'):
                ReadOnlyExplorerSQLiteRepository(str(path)).read_track(tid)

    def test_non_object_stage_payload_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'analysis.sqlite'
            db = create_db(path)
            tid = 'sha256:' + 'a' * 64
            db.execute('INSERT INTO tracks VALUES(?,?,?)', (tid, 'a' * 64, 10))
            db.execute('INSERT INTO runs(id,location,status,detail) VALUES(?,?,?,?)', ('run', '', 'completed', ''))
            db.execute('INSERT INTO run_tracks VALUES(?,?)', ('run', tid))
            db.execute('INSERT INTO stages VALUES(?,?,?)', ('run', 'bpm', '[]'))
            db.commit(); db.close()
            with self.assertRaisesRegex(AnalysisError, 'Invalid stored stage'):
                ReadOnlyExplorerSQLiteRepository(str(path)).read_track(tid)

    def test_list_tracks_reads_page_and_records_in_one_transaction(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'analysis.sqlite'
            db = create_db(path)
            first = 'sha256:' + '1' * 64
            second = 'sha256:' + '2' * 64
            for tid in (first, second):
                db.execute('INSERT INTO tracks VALUES(?,?,?)', (tid, tid.split(':')[1], 10))
            db.execute('INSERT INTO locations VALUES(?,?,?,?,?)', ('/private/music/First.flac', first, 1, 'flac', 1))
            db.commit(); db.close()
            metadata, track_count, tracks = ReadOnlyExplorerSQLiteRepository(str(path)).list_tracks(limit=1)
            self.assertEqual(metadata['read_policy'], 'bounded_read_transaction')
            self.assertEqual(track_count, 2)
            self.assertEqual(tuple(track.track_id for track in tracks), (first,))
            self.assertEqual(tracks[0].display_label, 'First.flac')


if __name__ == '__main__':
    unittest.main()
