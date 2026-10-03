import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from music_analyzer.application.dto.analysis import AnalysisError
from music_analyzer.domain.projection import ProjectionEdge
from music_analyzer.infrastructure.persistence.analysis import APPLICATION_ID, SQLiteAnalysisRepository
from music_analyzer.infrastructure.persistence.explorer_readonly import ReadOnlyExplorerSQLiteRepository


TRACKS = {
    'a': 'sha256:' + 'a' * 64,
    'b': 'sha256:' + 'b' * 64,
    'c': 'sha256:' + 'c' * 64,
}


def stage_payload(stage, *, bpm=None, arousal=None):
    values = () if bpm is None else (('bpm', bpm),)
    payload = {
        'stage': stage,
        'provenance': [['fixture', 'issue44-lifecycle-red']],
        'uncertainty': '',
        'values': [list(item) for item in values],
    }
    if arousal is not None:
        payload['summary'] = {
            'labels': ['arousal'],
            'mean': [arousal],
            'minimum': [arousal],
            'maximum': [arousal],
            'coverage': 1.0,
            'provisional': False,
            'uncertainty': '',
        }
    return json.dumps(payload)


def create_v6_candidate_database(path: Path) -> None:
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
        for suffix, bpm, arousal in (('a', 100.0, 0.0), ('b', 200.0, 1.0), ('c', 100.0, 2.0)):
            track_id = TRACKS[suffix]
            run_id = 'run-' + suffix
            db.execute('INSERT INTO tracks VALUES(?,?,?)', (track_id, suffix * 64, 100 + ord(suffix)))
            db.execute('INSERT INTO locations VALUES(?,?,?,?,?)', (f'/music/{suffix}.flac', track_id, ord(suffix), 'flac', 1))
            db.execute('INSERT INTO scan_roots VALUES(?,?)', ('/music', f'/music/{suffix}.flac'))
            db.execute('INSERT INTO runs VALUES(?,?,?,?,?)', (run_id, f'/music/{suffix}.flac', 'completed', 'ok', f'then-{suffix}'))
            db.execute('INSERT INTO run_tracks VALUES(?,?)', (run_id, track_id))
            db.execute('INSERT INTO stages VALUES(?,?,?)', (run_id, 'bpm', stage_payload('bpm', bpm=bpm)))
            db.execute('INSERT INTO stages VALUES(?,?,?)', (run_id, 'energy', stage_payload('energy', arousal=arousal)))
            db.execute('INSERT INTO track_metadata VALUES(?,?,?,?)', (track_id, f'[["title","Track {suffix}"]]', '[]', '[]'))
            db.execute('INSERT INTO track_audio VALUES(?,?,?,?,?)', (track_id, 180.0, 'mutagen', 'eligible', ''))


class GraphBuildLifecycleRedTests(unittest.TestCase):
    def test_v9_database_migrates_to_v10_with_non_current_build_attempt_states(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'analysis.sqlite'
            create_v6_candidate_database(path)

            SQLiteAnalysisRepository(str(path))

            with closing(sqlite3.connect(path)) as db:
                self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0], 10)
                sql = ' '.join(db.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='graph_builds'").fetchone()[0].split())
                self.assertIn("'building'", sql)
                self.assertIn("'interrupted'", sql)
                self.assertIn('source_revision', sql)
                self.assertIn('attempt_revision', sql)
                for status in ('building', 'interrupted', 'failed'):
                    db.execute('''
                        INSERT INTO graph_builds(
                            id,status,detail,edge_count,sparse_k,source_fingerprint,source_revision,attempt_revision,
                            distance_policy_version,neighbour_policy_version,is_current
                        ) VALUES(?,?,?,?,?,?,?,?,?,?,0)
                    ''', (f'{status}-attempt', status, status, 0, 10, 'fp-' + status, 'rev-1', 'attempt-1', 'distance-test', 'neighbour-test'))

    def test_read_only_explorer_reports_building_attempt_without_publishing_partial_edges(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'analysis.sqlite'
            create_v6_candidate_database(path)
            SQLiteAnalysisRepository(str(path))
            with closing(sqlite3.connect(path)) as db, db:
                self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0], 10)
                db.execute('''
                    INSERT INTO graph_builds(
                        id,status,detail,edge_count,sparse_k,source_fingerprint,source_revision,attempt_revision,
                        distance_policy_version,neighbour_policy_version,is_current
                    ) VALUES('build-in-progress','building','explicit graph build is running',0,10,'fp-building','rev-1','attempt-1','distance-test','neighbour-test',0)
                ''')
                db.execute('''
                    INSERT INTO graph_build_edges(
                        build_id,source_track_id,target_track_id,score,distance,supported_group_count,
                        distance_policy_version,neighbour_policy_version,built_at
                    ) VALUES('build-in-progress',?,?,?,?,?,?,?,CURRENT_TIMESTAMP)
                ''', (TRACKS['a'], TRACKS['b'], 0.5, 0.5, 2, 'distance-test', 'neighbour-test'))

            status, edges = ReadOnlyExplorerSQLiteRepository(str(path)).current_graph_edges()

            self.assertEqual(status['state'], 'building')
            self.assertIn('explicit graph build is running', status['reason'])
            self.assertEqual(edges, ())

    def test_interrupted_attempt_is_never_current_and_retry_can_promote_new_completed_build(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'analysis.sqlite'
            create_v6_candidate_database(path)
            repository = SQLiteAnalysisRepository(str(path))
            with closing(sqlite3.connect(path)) as db, db:
                self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0], 10)
                db.execute('''
                    INSERT INTO graph_builds(
                        id,status,detail,edge_count,sparse_k,source_fingerprint,source_revision,attempt_revision,
                        distance_policy_version,neighbour_policy_version,is_current
                    ) VALUES('killed-attempt','interrupted','worker received SIGKILL before promote',0,10,'old-fp','old-rev','attempt-1','distance-test','neighbour-test',0)
                ''')

            completed = repository.replace_graph_snapshot((
                ProjectionEdge(TRACKS['a'], TRACKS['b'], 0.25, 2),
            ), 10, 'retry-fingerprint')

            with closing(sqlite3.connect(path)) as db:
                self.assertEqual(db.execute("SELECT is_current FROM graph_builds WHERE id='killed-attempt'").fetchone()[0], 0)
                self.assertEqual(db.execute('SELECT id,status,is_current FROM graph_builds WHERE is_current=1').fetchone(), (completed, 'completed', 1))
                self.assertEqual(db.execute('SELECT source_track_id,target_track_id FROM graph_edges').fetchone(), (TRACKS['a'], TRACKS['b']))

    def test_writer_mutation_between_source_capture_and_promote_cannot_publish_obsolete_snapshot(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'analysis.sqlite'
            create_v6_candidate_database(path)
            repository = SQLiteAnalysisRepository(str(path))
            stale_build = repository.replace_graph_snapshot((
                ProjectionEdge(TRACKS['a'], TRACKS['b'], 0.25, 2),
            ), 10, 'fingerprint-before-writer-mutation')
            with closing(sqlite3.connect(path)) as db, db:
                db.execute(
                    'UPDATE stages SET result=? WHERE run_id=? AND stage=?',
                    (stage_payload('bpm', bpm=123.0), 'run-a', 'bpm'),
                )
                db.execute('UPDATE graph_builds SET is_current=0 WHERE id=?', (stale_build,))
                db.execute('DELETE FROM graph_edges')

            with self.assertRaises(AnalysisError):
                repository.replace_graph_snapshot((
                    ProjectionEdge(TRACKS['a'], TRACKS['b'], 0.25, 2),
                ), 10, 'fingerprint-before-writer-mutation')
            with closing(sqlite3.connect(path)) as db:
                self.assertEqual(db.execute('SELECT count(*) FROM graph_builds WHERE is_current=1').fetchone()[0], 0)
                self.assertEqual(db.execute('SELECT count(*) FROM graph_edges').fetchone()[0], 0)


if __name__ == '__main__':
    unittest.main()
