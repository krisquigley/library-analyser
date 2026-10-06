import json
import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import urlopen

from music_analyzer.domain.projection import DISTANCE_POLICY_VERSION, NEIGHBOUR_POLICY_VERSION
from music_explorer.frameworks.explorer.server import create_server

APP_ID = 0x4D414E41


def _stage(name, value):
    return json.dumps({
        'stage': name,
        'provenance': [['fixture', 'red-test']],
        'uncertainty': '',
        'values': [[name, value]],
    })


def _create_playlist_http_db(path: Path, first_path: Path, second_path: Path):
    first = 'sha256:' + '1' * 64
    second = 'sha256:' + '2' * 64
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
    for index, (track_id, track_path, bpm) in enumerate(((first, first_path, 120.0), (second, second_path, 124.0)), start=1):
        db.execute('INSERT INTO tracks VALUES(?,?,?)', (track_id, track_id.split(':')[1], 10))
        db.execute('INSERT INTO locations VALUES(?,?,?,?,?)', (str(track_path), track_id, index, 'flac', 1))
        db.execute('INSERT INTO runs(id,location,status,detail) VALUES(?,?,?,?)', (f'run-{index}', str(track_path), 'completed', ''))
        db.execute('INSERT INTO run_tracks VALUES(?,?)', (f'run-{index}', track_id))
        db.execute('INSERT INTO stages VALUES(?,?,?)', (f'run-{index}', 'bpm', _stage('bpm', bpm)))
        db.execute('INSERT INTO track_audio VALUES(?,?,?,?,?)', (track_id, 120.0, 'mutagen', 'eligible', ''))
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
        first, second, 0.95, 0.05, 1,
        DISTANCE_POLICY_VERSION, NEIGHBOUR_POLICY_VERSION))
    db.execute('''INSERT INTO graph_build_edges(
        build_id,source_track_id,target_track_id,score,distance,supported_group_count,
        distance_policy_version,neighbour_policy_version)
        VALUES(?,?,?,?,?,?,?,?)''', (
        'playlist-build', first, second, 0.95, 0.05, 1,
        DISTANCE_POLICY_VERSION, NEIGHBOUR_POLICY_VERSION))
    db.commit()
    db.close()
    return first, second


def _table_counts(path: Path):
    with sqlite3.connect(path) as db:
        return {
            table: db.execute(f'SELECT count(*) FROM {table}').fetchone()[0]
            for table in ('tracks', 'locations', 'graph_builds', 'graph_edges', 'graph_build_edges', 'runs', 'stages')
        }


class ExplorerM3UPlaylistHTTPRedTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.first_path = root / 'First.flac'
        self.second_path = root / 'Second.flac'
        self.first_path.write_bytes(b'existence only; server must not read audio bytes')
        self.second_path.write_bytes(b'existence only; server must not read audio bytes')
        self.db_path = root / 'analysis.sqlite'
        self.first, self.second = _create_playlist_http_db(self.db_path, self.first_path, self.second_path)
        self.server = create_server(str(self.db_path), host='127.0.0.1', port=0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.server.shutdown)
        self.addCleanup(self.server.server_close)
        self.base = f'http://127.0.0.1:{self.server.server_port}'

    def _get(self, path):
        return urlopen(self.base + path, timeout=5)

    def test_download_m3u_endpoint_is_explicit_attachment_and_does_not_mutate_readonly_database(self):
        before_counts = _table_counts(self.db_path)
        before_bytes = self.db_path.read_bytes()

        with self._get('/api/state') as response:
            self.assertEqual(response.headers.get_content_type(), 'application/json')
        with self._get('/api/tracks?limit=all') as response:
            self.assertEqual(response.headers.get_content_type(), 'application/json')
        self.assertEqual(_table_counts(self.db_path), before_counts)
        self.assertEqual(self.db_path.read_bytes(), before_bytes)

        query = urlencode({
            'start_track_id': self.first,
            'bpm_min': '119',
            'bpm_max': '125',
            'length': '2',
        })
        try:
            response = self._get('/api/playlists/m3u?' + query)
        except HTTPError as error:
            self.fail(f'expected Issue #58 playlist endpoint to return 200 attachment, got HTTP {error.code}: {error.read().decode("utf-8", "replace")}')

        with response:
            body = response.read().decode('utf-8')
            self.assertEqual(response.status, 200)
            self.assertIn(response.headers.get_content_type(), {'audio/x-mpegurl', 'application/vnd.apple.mpegurl'})
            self.assertIn('charset=utf-8', response.headers.get('Content-Type', '').lower())
            self.assertIn('attachment', response.headers.get('Content-Disposition', '').lower())
            self.assertIn('library-graph-playlist.m3u', response.headers.get('Content-Disposition', ''))
        self.assertEqual(body, f'#EXTM3U\n{self.first_path}\n{self.second_path}\n')
        self.assertEqual(_table_counts(self.db_path), before_counts)
        self.assertEqual(self.db_path.read_bytes(), before_bytes)

    def test_download_m3u_endpoint_propagates_dead_end_warning_safely(self):
        query = urlencode({
            'start_track_id': self.first,
            'bpm_min': '119',
            'bpm_max': '125',
            'length': '3',
        })

        with self._get('/api/playlists/m3u?' + query) as response:
            body = response.read().decode('utf-8')
            warning = response.headers.get('X-Music-Explorer-Playlist-Warning')

        self.assertEqual(response.status, 200)
        self.assertIsNotNone(warning)
        self.assertIn('shorter than requested', warning)
        self.assertIn('dead end', warning)
        self.assertNotRegex(warning, r'[\r\n<>]')
        self.assertEqual(body.splitlines()[0], '#EXTM3U')
        self.assertIn('#PLAYLIST-WARNING: ', body)
        self.assertIn('shorter than requested', body)
        self.assertIn(str(self.first_path), body)
        self.assertIn(str(self.second_path), body)
        self.assertNotIn('<', body)
        self.assertNotIn('>', body)

        branch_query = urlencode({
            'start_track_id': self.first,
            'bpm_min': '119',
            'bpm_max': '125',
            'length': '2',
        })
        with self._get('/api/playlists/m3u?' + branch_query) as complete_response:
            self.assertIsNone(complete_response.headers.get('X-Music-Explorer-Playlist-Warning'))
            self.assertNotIn('#PLAYLIST-WARNING:', complete_response.read().decode('utf-8'))

    def test_download_m3u_endpoint_reports_validation_errors_as_json_400(self):
        invalid_query = urlencode({'start_track_id': '', 'bpm_min': '130', 'bpm_max': '120', 'length': '0'})
        with self.assertRaises(HTTPError) as raised:
            self._get('/api/playlists/m3u?' + invalid_query)

        self.assertEqual(raised.exception.code, 400)
        self.assertEqual(raised.exception.headers.get_content_type(), 'application/json')
        payload = json.loads(raised.exception.read().decode('utf-8'))
        self.assertIn('error', payload)
        self.assertRegex(payload['error'], 'start|bpm|length')


if __name__ == '__main__':
    unittest.main()
