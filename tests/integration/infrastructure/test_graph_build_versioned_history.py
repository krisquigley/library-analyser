import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from music_analyzer.frameworks.cli.main import main
from music_analyzer.infrastructure.persistence.analysis import APPLICATION_ID
from music_analyzer.infrastructure.persistence.explorer_readonly import ReadOnlyExplorerSQLiteRepository
from music_explorer.infrastructure.explorer_readonly import ReadOnlyExplorerSQLiteRepository as StandaloneReadOnlyExplorerSQLiteRepository


TRACKS = {
    'a': 'sha256:' + 'a' * 64,
    'b': 'sha256:' + 'b' * 64,
    'c': 'sha256:' + 'c' * 64,
}


def stage_payload(stage, *, values=(), summary=None):
    data = {
        'stage': stage,
        'provenance': [['fixture', 'versioned-history']],
        'uncertainty': '',
        'values': [list(item) for item in values],
    }
    if summary is not None:
        labels, mean = summary
        data['summary'] = {
            'labels': list(labels),
            'mean': list(mean),
            'minimum': list(mean),
            'maximum': list(mean),
            'coverage': 1.0,
            'provisional': False,
            'uncertainty': '',
        }
    return json.dumps(data)


def create_candidate_database(path: Path) -> None:
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
        fixtures = (('a', 100.0, 0.0), ('b', 200.0, 1.0), ('c', 100.0, 2.0))
        for suffix, bpm, arousal in fixtures:
            track_id = TRACKS[suffix]
            run_id = 'run-' + suffix
            db.execute('INSERT INTO tracks VALUES(?,?,?)', (track_id, suffix * 64, 100 + ord(suffix)))
            db.execute('INSERT INTO locations VALUES(?,?,?,?,?)', (f'/music/{suffix}.flac', track_id, ord(suffix), 'flac', 1))
            db.execute('INSERT INTO scan_roots VALUES(?,?)', ('/music', f'/music/{suffix}.flac'))
            db.execute('INSERT INTO runs VALUES(?,?,?,?,?)', (run_id, f'/music/{suffix}.flac', 'completed', 'ok', f'then-{suffix}'))
            db.execute('INSERT INTO run_tracks VALUES(?,?)', (run_id, track_id))
            db.execute('INSERT INTO stages VALUES(?,?,?)', (run_id, 'bpm', stage_payload('bpm', values=(('bpm', bpm),))))
            db.execute('INSERT INTO stages VALUES(?,?,?)', (run_id, 'energy', stage_payload('energy', summary=(('arousal',), (arousal,)))))
            db.execute('INSERT INTO track_metadata VALUES(?,?,?,?)', (track_id, '[]', '[]', '[]'))
            db.execute('INSERT INTO track_audio VALUES(?,?,?,?,?)', (track_id, 180.0, 'mutagen', 'eligible', ''))


def build(path: Path) -> None:
    result = main(['graph', 'build', '--database', str(path)])
    if result != 0:
        raise AssertionError(result)


class GraphBuildVersionedHistoryTests(unittest.TestCase):
    def test_repeated_builds_retain_edges_by_build_id_and_one_current_completed_build(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'analysis.sqlite'
            create_candidate_database(path)
            build(path)
            with closing(sqlite3.connect(path)) as db, db:
                first_build = db.execute('SELECT id FROM graph_builds WHERE is_current=1').fetchone()[0]
                db.execute("UPDATE runs SET status='failed', detail='synthetic stale evidence' WHERE id=?", ('run-c',))
            build(path)
            build(path)
            with closing(sqlite3.connect(path)) as db:
                builds = tuple(db.execute('SELECT id,status,is_current,edge_count FROM graph_builds ORDER BY created_at,id'))
                self.assertEqual(len(builds), 3)
                self.assertEqual(sum(row[2] for row in builds if row[1] == 'completed'), 1)
                current_build = db.execute('SELECT id FROM graph_builds WHERE status="completed" AND is_current=1').fetchone()[0]
                self.assertNotEqual(first_build, current_build)
                self.assertEqual(db.execute('SELECT count(*) FROM graph_edges').fetchone()[0], 1)
                self.assertEqual(db.execute('SELECT count(*) FROM graph_build_edges WHERE build_id=?', (first_build,)).fetchone()[0], 3)
                self.assertEqual(db.execute('SELECT count(*) FROM graph_build_edges WHERE build_id=?', (current_build,)).fetchone()[0], 1)
                fk_targets = tuple((row[3], row[2], row[4]) for row in db.execute('PRAGMA foreign_key_list(graph_build_edges)'))
                self.assertIn(('build_id', 'graph_builds', 'id'), fk_targets)
                indexes = {row[1] for row in db.execute('PRAGMA index_list(graph_build_edges)')}
                self.assertIn('idx_graph_build_edges_build_id', indexes)
                self.assertIn('idx_graph_build_edges_source_track_id', indexes)
                self.assertIn('idx_graph_build_edges_target_track_id', indexes)

    def test_readonly_validators_reject_invalid_graph_build_rows(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'analysis.sqlite'
            create_candidate_database(path)
            build(path)
            cases = (
                "UPDATE graph_builds SET status='running'",
                "UPDATE graph_builds SET edge_count=-1",
                "UPDATE graph_builds SET distance_policy_version='bad'",
                "UPDATE graph_builds SET is_current=0",
            )
            for sql in cases:
                case_path = Path(td) / (str(abs(hash(sql))) + '.sqlite')
                case_path.write_bytes(path.read_bytes())
                with closing(sqlite3.connect(case_path)) as db, db:
                    db.execute('PRAGMA ignore_check_constraints=ON')
                    db.execute(sql)
                with self.assertRaises(Exception):
                    ReadOnlyExplorerSQLiteRepository(str(case_path)).metadata()
                with self.assertRaises(Exception):
                    StandaloneReadOnlyExplorerSQLiteRepository(str(case_path)).metadata()
            ReadOnlyExplorerSQLiteRepository(str(path)).metadata()
            StandaloneReadOnlyExplorerSQLiteRepository(str(path)).metadata()


if __name__ == '__main__':
    unittest.main()
