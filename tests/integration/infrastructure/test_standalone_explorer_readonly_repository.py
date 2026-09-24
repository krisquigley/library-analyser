import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from music_exporer.infrastructure.explorer_readonly import AnalysisError, ReadOnlyExplorerSQLiteRepository

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


class StandaloneReadOnlyExplorerSQLiteRepositoryTests(unittest.TestCase):
    def test_rejects_malformed_stage_summary_with_empty_labels_and_zero_coverage(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'analysis.sqlite'
            db = create_db(path)
            tid = 'sha256:' + 'b' * 64
            db.execute('INSERT INTO tracks VALUES(?,?,?)', (tid, 'b' * 64, 10))
            db.execute('INSERT INTO runs(id,location,status,detail) VALUES(?,?,?,?)', ('run', '', 'completed', ''))
            db.execute('INSERT INTO run_tracks VALUES(?,?)', ('run', tid))
            payload = {
                'stage': 'energy',
                'provenance': [],
                'uncertainty': '',
                'values': [],
                'summary': {'labels': [], 'mean': [], 'minimum': [], 'maximum': [], 'coverage': 0},
            }
            db.execute('INSERT INTO stages VALUES(?,?,?)', ('run', 'energy', json.dumps(payload)))
            db.commit(); db.close()
            with self.assertRaisesRegex(AnalysisError, 'Invalid stored stage'):
                ReadOnlyExplorerSQLiteRepository(str(path)).read_track(tid)

    def test_rejects_boolean_stage_summary_numbers(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'analysis.sqlite'
            db = create_db(path)
            tid = 'sha256:' + 'b' * 64
            db.execute('INSERT INTO tracks VALUES(?,?,?)', (tid, 'b' * 64, 10))
            db.execute('INSERT INTO runs(id,location,status,detail) VALUES(?,?,?,?)', ('run', '', 'completed', ''))
            db.execute('INSERT INTO run_tracks VALUES(?,?)', ('run', tid))
            payload = {
                'stage': 'mood',
                'provenance': [],
                'uncertainty': '',
                'values': [['valence', True]],
                'summary': {
                    'labels': ['valence'],
                    'mean': [True],
                    'minimum': [0.0],
                    'maximum': [1.0],
                    'coverage': 1.0,
                },
            }
            db.execute('INSERT INTO stages VALUES(?,?,?)', ('run', 'mood', json.dumps(payload)))
            db.commit(); db.close()
            with self.assertRaisesRegex(AnalysisError, 'Invalid stored stage'):
                ReadOnlyExplorerSQLiteRepository(str(path)).read_track(tid)

    def test_rejects_boolean_stage_summary_coverage(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'analysis.sqlite'
            db = create_db(path)
            tid = 'sha256:' + 'b' * 64
            db.execute('INSERT INTO tracks VALUES(?,?,?)', (tid, 'b' * 64, 10))
            db.execute('INSERT INTO runs(id,location,status,detail) VALUES(?,?,?,?)', ('run', '', 'completed', ''))
            db.execute('INSERT INTO run_tracks VALUES(?,?)', ('run', tid))
            payload = {
                'stage': 'mood',
                'provenance': [],
                'uncertainty': '',
                'values': [['valence', 0.5]],
                'summary': {
                    'labels': ['valence'],
                    'mean': [0.5],
                    'minimum': [0.0],
                    'maximum': [1.0],
                    'coverage': True,
                },
            }
            db.execute('INSERT INTO stages VALUES(?,?,?)', ('run', 'mood', json.dumps(payload)))
            db.commit(); db.close()
            with self.assertRaisesRegex(AnalysisError, 'Invalid stored stage'):
                ReadOnlyExplorerSQLiteRepository(str(path)).read_track(tid)


if __name__ == '__main__':
    unittest.main()
