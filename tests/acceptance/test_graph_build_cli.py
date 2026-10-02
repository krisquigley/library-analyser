import contextlib
import io
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from music_analyzer.frameworks.cli.main import main
from music_analyzer.infrastructure.persistence.analysis import APPLICATION_ID


TRACKS = {
    'a': 'sha256:' + 'a' * 64,
    'b': 'sha256:' + 'b' * 64,
    'c': 'sha256:' + 'c' * 64,
}


def stage_payload(stage, *, values=(), summary=None, model='fixture-model'):
    data = {
        'stage': stage,
        'provenance': [['model', model], ['fixture', 'issue44-red']],
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
        fixtures = (
            ('a', 100.0, 0.0),
            ('b', 200.0, 1.0),
            ('c', 100.0, 2.0),
        )
        for suffix, bpm, arousal in fixtures:
            track_id = TRACKS[suffix]
            run_id = 'run-' + suffix
            db.execute('INSERT INTO tracks VALUES(?,?,?)', (track_id, suffix * 64, 100 + ord(suffix)))
            db.execute('INSERT INTO locations VALUES(?,?,?,?,?)', (f'/music/{suffix.upper()}.flac', track_id, ord(suffix), 'flac', 1))
            db.execute('INSERT INTO scan_roots VALUES(?,?)', ('/music', f'/music/{suffix.upper()}.flac'))
            db.execute('INSERT INTO runs VALUES(?,?,?,?,?)', (run_id, f'/music/{suffix.upper()}.flac', 'completed', 'ok', f'then-{suffix}'))
            db.execute('INSERT INTO run_tracks VALUES(?,?)', (run_id, track_id))
            db.execute('INSERT INTO stages VALUES(?,?,?)', (run_id, 'bpm', stage_payload('bpm', values=(('bpm', bpm),))))
            db.execute('INSERT INTO stages VALUES(?,?,?)', (run_id, 'energy', stage_payload('energy', summary=(('arousal',), (arousal,)))))
            db.execute('INSERT INTO track_metadata VALUES(?,?,?,?)', (track_id, f'[["title","Track {suffix.upper()}"]]', '[]', '[]'))
            db.execute('INSERT INTO track_audio VALUES(?,?,?,?,?)', (track_id, 180.0, 'mutagen', 'eligible', ''))
        # Retained but incomplete evidence must not become an inferred edge endpoint.
        db.execute('INSERT INTO tracks VALUES(?,?,?)', ('sha256:' + 'd' * 64, 'd' * 64, 104))
        db.execute('INSERT INTO track_audio VALUES(?,?,?,?,?)', ('sha256:' + 'd' * 64, 180.0, 'mutagen', 'eligible', ''))


class GraphBuildCLITests(unittest.TestCase):
    def test_graph_build_persists_exact_current_bounded_edges_without_audio_or_model_reads(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'analysis.sqlite'
            create_candidate_database(path)

            with (
                patch('music_analyzer.frameworks.cli.main.build_analysis', side_effect=AssertionError('graph build must not build analysis')) as build_analysis,
                patch('music_analyzer.frameworks.cli.main.build_batch_worker', side_effect=AssertionError('graph build must not build batch worker')) as build_batch_worker,
                patch('music_analyzer.frameworks.cli.main.MutagenMetadataReader.read', side_effect=AssertionError('graph build must not read audio metadata')) as read_audio,
                patch('music_analyzer.frameworks.cli.main.load_backend', side_effect=AssertionError('graph build must not load inference backend')) as load_backend,
                contextlib.redirect_stdout(io.StringIO()) as stdout,
                contextlib.redirect_stderr(io.StringIO()),
            ):
                try:
                    result = main(['graph', 'build', '--database', str(path)])
                except SystemExit as error:
                    result = error.code
                self.assertEqual(result, 0)

            self.assertIn('Built 3 graph edges', stdout.getvalue())
            build_analysis.assert_not_called()
            build_batch_worker.assert_not_called()
            read_audio.assert_not_called()
            load_backend.assert_not_called()

            with closing(sqlite3.connect(path)) as db:
                self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0], 8)
                self.assertEqual(
                    tuple(db.execute('''
                        SELECT source_track_id,target_track_id,score,distance,supported_group_count,distance_policy_version,neighbour_policy_version
                        FROM graph_edges ORDER BY source_track_id,target_track_id
                    ''')),
                    (
                        (TRACKS['a'], TRACKS['b'], 0.25, 0.75, 2, 'symmetric-feature-distance-v1', 'endpoint-local-exact-top-k-neighbours-v2'),
                        (TRACKS['a'], TRACKS['c'], 0.5, 0.5, 2, 'symmetric-feature-distance-v1', 'endpoint-local-exact-top-k-neighbours-v2'),
                        (TRACKS['b'], TRACKS['c'], 0.25, 0.75, 2, 'symmetric-feature-distance-v1', 'endpoint-local-exact-top-k-neighbours-v2'),
                    ),
                )
                self.assertEqual(db.execute('SELECT count(*) FROM runs WHERE status="completed"').fetchone()[0], 3)
                self.assertEqual(db.execute('SELECT count(*) FROM stages').fetchone()[0], 6)


if __name__ == '__main__':
    unittest.main()
