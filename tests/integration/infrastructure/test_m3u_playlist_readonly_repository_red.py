import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from music_analyzer.domain.projection import DISTANCE_POLICY_VERSION, NEIGHBOUR_POLICY_VERSION
from music_explorer.infrastructure.explorer_readonly import ReadOnlyExplorerSQLiteRepository

APP_ID = 0x4D414E41


def _stage(name, value):
    return json.dumps({
        'stage': name,
        'provenance': [['fixture', 'red-test']],
        'uncertainty': '',
        'values': [[name, value]],
    })


def _create_playlist_fixture_db(path: Path, playable_paths: dict[str, Path]):
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
CREATE TABLE track_metadata(track_id TEXT PRIMARY KEY REFERENCES tracks(id), common_json TEXT NOT NULL, tags_json TEXT NOT NULL, warnings_json TEXT NOT NULL);
CREATE TABLE track_audio(track_id TEXT PRIMARY KEY REFERENCES tracks(id), duration_seconds REAL, duration_source TEXT NOT NULL, status TEXT NOT NULL CHECK(status IN ('eligible','excluded','unknown')), reason TEXT NOT NULL);
CREATE VIEW active_tracks AS SELECT t.id,t.sha256,t.size FROM tracks t JOIN track_audio a ON a.track_id=t.id WHERE a.status='eligible';
CREATE VIEW active_locations AS SELECT l.path,l.track_id,l.mtime_ns,l.format,l.available FROM locations l JOIN track_audio a ON a.track_id=l.track_id WHERE l.available=1 AND a.status='eligible';
CREATE TABLE graph_builds(
    id TEXT PRIMARY KEY,
    status TEXT NOT NULL CHECK(status IN ('completed','failed')),
    detail TEXT NOT NULL,
    edge_count INTEGER NOT NULL CHECK(edge_count >= 0),
    sparse_k INTEGER NOT NULL CHECK(sparse_k >= 0),
    source_fingerprint TEXT NOT NULL,
    distance_policy_version TEXT NOT NULL,
    neighbour_policy_version TEXT NOT NULL,
    is_current INTEGER NOT NULL CHECK(is_current IN (0,1)),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CHECK(status = 'completed' OR is_current = 0));
CREATE UNIQUE INDEX idx_graph_builds_one_current ON graph_builds(is_current) WHERE is_current = 1;
CREATE TABLE graph_edges(
    source_track_id TEXT NOT NULL REFERENCES tracks(id),
    target_track_id TEXT NOT NULL REFERENCES tracks(id),
    score REAL NOT NULL CHECK(score >= 0.0 AND score <= 1.0),
    distance REAL NOT NULL CHECK(distance >= 0.0 AND distance <= 1.0),
    supported_group_count INTEGER NOT NULL CHECK(supported_group_count > 0),
    distance_policy_version TEXT NOT NULL,
    neighbour_policy_version TEXT NOT NULL,
    built_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY(source_track_id,target_track_id),
    CHECK(source_track_id < target_track_id));
CREATE INDEX idx_graph_edges_source_track_id ON graph_edges(source_track_id);
CREATE INDEX idx_graph_edges_target_track_id ON graph_edges(target_track_id);
CREATE TABLE graph_build_edges(
    build_id TEXT NOT NULL REFERENCES graph_builds(id) ON DELETE CASCADE,
    source_track_id TEXT NOT NULL REFERENCES tracks(id),
    target_track_id TEXT NOT NULL REFERENCES tracks(id),
    score REAL NOT NULL CHECK(score >= 0.0 AND score <= 1.0),
    distance REAL NOT NULL CHECK(distance >= 0.0 AND distance <= 1.0),
    supported_group_count INTEGER NOT NULL CHECK(supported_group_count > 0),
    distance_policy_version TEXT NOT NULL,
    neighbour_policy_version TEXT NOT NULL,
    built_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY(build_id,source_track_id,target_track_id),
    CHECK(source_track_id < target_track_id));
CREATE INDEX idx_graph_build_edges_build_id ON graph_build_edges(build_id);
CREATE INDEX idx_graph_build_edges_source_track_id ON graph_build_edges(build_id,source_track_id);
CREATE INDEX idx_graph_build_edges_target_track_id ON graph_build_edges(build_id,target_track_id);
''')
    db.execute(f'PRAGMA application_id={APP_ID}')
    db.execute('PRAGMA user_version=7')
    rows = [
        ('sha256:' + '1' * 64, 118.0, 'eligible', 1),
        ('sha256:' + '2' * 64, 122.0, 'eligible', 1),
        ('sha256:' + '3' * 64, 126.0, 'excluded', 1),
        ('sha256:' + '4' * 64, 124.0, 'eligible', 0),
    ]
    for index, (track_id, bpm, status, available) in enumerate(rows, start=1):
        db.execute('INSERT INTO tracks VALUES(?,?,?)', (track_id, track_id.split(':')[1], 10))
        db.execute('INSERT INTO locations VALUES(?,?,?,?,?)', (str(playable_paths[track_id]), track_id, index, 'flac', available))
        db.execute('INSERT INTO runs(id,location,status,detail) VALUES(?,?,?,?)', (f'run-{index}', str(playable_paths[track_id]), 'completed', ''))
        db.execute('INSERT INTO run_tracks VALUES(?,?)', (f'run-{index}', track_id))
        db.execute('INSERT INTO stages VALUES(?,?,?)', (f'run-{index}', 'bpm', _stage('bpm', bpm)))
        db.execute('INSERT INTO track_audio VALUES(?,?,?,?,?)', (track_id, 120.0, 'mutagen', status, '' if status == 'eligible' else 'excluded by fixture'))
    db.execute('''INSERT INTO graph_builds(
        id,status,detail,edge_count,sparse_k,source_fingerprint,
        distance_policy_version,neighbour_policy_version,is_current,created_at,completed_at)
        VALUES(?,?,?,?,?,?,?,?,?,?,?)''', (
        'playlist-build', 'completed', '', 1, 10, 'fixture',
        DISTANCE_POLICY_VERSION, NEIGHBOUR_POLICY_VERSION, 1, 'created', 'completed'))
    db.execute('''INSERT INTO graph_edges(
        source_track_id,target_track_id,score,distance,supported_group_count,
        distance_policy_version,neighbour_policy_version)
        VALUES(?,?,?,?,?,?,?)''', (
        'sha256:' + '1' * 64, 'sha256:' + '2' * 64, 0.91, 0.09, 1,
        DISTANCE_POLICY_VERSION, NEIGHBOUR_POLICY_VERSION))
    db.execute('''INSERT INTO graph_build_edges(
        build_id,source_track_id,target_track_id,score,distance,supported_group_count,
        distance_policy_version,neighbour_policy_version)
        VALUES(?,?,?,?,?,?,?,?)''', (
        'playlist-build', 'sha256:' + '1' * 64, 'sha256:' + '2' * 64, 0.91, 0.09, 1,
        DISTANCE_POLICY_VERSION, NEIGHBOUR_POLICY_VERSION))
    db.commit()
    db.close()


class M3UPlaylistReadOnlyRepositoryRedTests(unittest.TestCase):
    def test_playlist_export_port_returns_only_active_available_existing_local_tracks_without_mutating_db_or_reading_audio(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            db_path = root / 'analysis.sqlite'
            track_ids = tuple('sha256:' + digit * 64 for digit in ('1', '2', '3', '4'))
            playable_paths = {track_id: root / f'{index}.flac' for index, track_id in enumerate(track_ids, start=1)}
            for path in playable_paths.values():
                path.write_bytes(b'not audio; existence sentinel only')
            _create_playlist_fixture_db(db_path, playable_paths)
            before = db_path.read_bytes()
            repository = ReadOnlyExplorerSQLiteRepository(str(db_path))
            export = getattr(repository, 'playlist_export_tracks', None)
            self.assertIsNotNone(
                export,
                'ReadOnlyExplorerSQLiteRepository must expose a read-only playlist_export_tracks() port for Issue #58',
            )

            with patch('builtins.open', side_effect=AssertionError('playlist export must not open/read audio file bytes')):
                candidates = export()

            self.assertEqual(db_path.read_bytes(), before, 'playlist export must not write or migrate the analysis database')
            self.assertEqual([candidate.track_id for candidate in candidates], [track_ids[0], track_ids[1]])
            self.assertEqual([candidate.bpm for candidate in candidates], [118.0, 122.0])
            self.assertEqual([candidate.path for candidate in candidates], [str(playable_paths[track_ids[0]]), str(playable_paths[track_ids[1]])])


if __name__ == '__main__':
    unittest.main()
