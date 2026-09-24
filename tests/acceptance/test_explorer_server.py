import json
import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import music_exporer.frameworks.explorer.server as standalone_server
from music_analyzer.frameworks.explorer.server import create_server

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
    first = 'sha256:' + '1' * 64
    second = 'sha256:' + '2' * 64
    for tid, label, bpm in ((first, 'First & Friend.flac', 120.0), (second, 'Second.flac', 124.0)):
        db.execute('INSERT INTO tracks VALUES(?,?,?)', (tid, tid.split(':')[1], 10))
        db.execute('INSERT INTO locations VALUES(?,?,?,?,?)', ('/music/' + label, tid, 1, 'flac', 1))
        db.execute('INSERT INTO runs(id,location,status,detail) VALUES(?,?,?,?)', ('run-' + tid[-1], '/music/' + label, 'completed', ''))
        db.execute('INSERT INTO run_tracks VALUES(?,?)', ('run-' + tid[-1], tid))
        db.execute('INSERT INTO stages VALUES(?,?,?)', ('run-' + tid[-1], 'bpm', json.dumps({'stage': 'bpm', 'provenance': [], 'uncertainty': '', 'values': [['bpm', bpm]]})))
    db.commit(); db.close()
    return first, second


class ExplorerServerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db = Path(self.temp.name) / 'analysis.sqlite'
        self.first, self.second = create_db(self.db)
        self.server = create_server(str(self.db), host='127.0.0.1', port=0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.server.shutdown)
        self.addCleanup(self.server.server_close)
        self.base = f'http://127.0.0.1:{self.server.server_port}'

    def get_json(self, path):
        with urlopen(self.base + path, timeout=5) as response:
            self.assertEqual(response.headers.get_content_type(), 'application/json')
            return json.loads(response.read().decode('utf-8'))

    def post_json(self, path, body=None):
        req = Request(self.base + path, data=json.dumps(body or {}).encode(), method='POST', headers={'Content-Type': 'application/json'})
        with urlopen(req, timeout=5) as response:
            self.assertEqual(response.headers.get_content_type(), 'application/json')
            return json.loads(response.read().decode('utf-8'))

    def post_current(self, track_id, selection_token=None):
        body = {'track_id': track_id}
        if selection_token is not None:
            body['selection_token'] = selection_token
        return self.post_json('/api/current', body)

    def test_api_lists_details_candidates_state_and_projection(self):
        state = self.get_json('/api/state')
        self.assertIsNone(state['current_track_id'])
        self.assertEqual(state['history'], [])
        listing = self.get_json('/api/tracks')
        self.assertEqual(listing['tracks'][0]['display_label'], 'First & Friend.flac')
        detail = self.get_json('/api/tracks/' + self.first)
        self.assertEqual(detail['fields']['bpm']['automatic']['values'], [['bpm', 120.0]])
        req = Request(self.base + '/api/current', data=json.dumps({'track_id': self.first}).encode(), method='POST', headers={'Content-Type': 'application/json'})
        with urlopen(req, timeout=5):
            pass
        candidates = self.get_json('/api/candidates?control=tempo:soft:1&limit=5')
        self.assertEqual(candidates['current_track_id'], self.first)
        self.assertEqual(candidates['controls_echo'][0]['name'], 'tempo')
        projection = self.get_json('/api/projection')
        self.assertEqual({p['track_id'] for p in projection['tracks']}, {self.first, self.second})
        self.assertIn('x', projection['tracks'][0])

    def test_projection_endpoint_computes_from_live_database_not_prepared_artifact(self):
        artifact = self.db.with_name('projection.json')
        artifact.write_text(json.dumps({'tracks': [{'track_id': 'not-from-server-artifact'}]}), encoding='utf-8')

        projection = self.get_json('/api/projection')

        self.assertEqual({p['track_id'] for p in projection['tracks']}, {self.first, self.second})
        self.assertNotIn('not-from-server-artifact', {p['track_id'] for p in projection['tracks']})

    def test_post_state_changes_are_explicit_and_request_bounded(self):
        req = Request(self.base + '/api/current', data=json.dumps({'track_id': self.second}).encode(), method='POST', headers={'Content-Type': 'application/json'})
        with urlopen(req, timeout=5) as response:
            self.assertEqual(response.status, 200)
        self.assertEqual(self.get_json('/api/state')['current_track_id'], self.second)
        req = Request(self.base + '/api/undo', data=b'{}', method='POST', headers={'Content-Type': 'application/json'})
        with urlopen(req, timeout=5):
            pass
        self.assertIsNone(self.get_json('/api/state')['current_track_id'])
        too_large = Request(self.base + '/api/current', data=(b'{' + b' ' * 70000 + b'}'), method='POST', headers={'Content-Type': 'application/json'})
        with self.assertRaises(HTTPError) as raised:
            urlopen(too_large, timeout=5)
        self.assertEqual(raised.exception.code, 413)

    def test_delayed_click_matching_reset_token_does_not_restore_selection(self):
        self.post_json('/api/reset')

        delayed = self.post_current(self.first, 1)

        self.assertIsNone(delayed['current_track_id'])
        self.assertEqual(delayed['history'], [])
        self.assertIsNone(self.get_json('/api/state')['current_track_id'])

    def test_delayed_click_matching_undo_token_does_not_restore_selection(self):
        self.post_current(self.first)
        self.post_current(self.second)
        self.post_json('/api/undo')

        delayed = self.post_current(self.second, 1)

        self.assertEqual(delayed['current_track_id'], self.first)
        self.assertEqual(delayed['history'], [None])
        self.assertEqual(self.get_json('/api/state')['current_track_id'], self.first)

    def test_valid_click_after_reset_and_undo_tokens_is_accepted(self):
        self.post_json('/api/reset')
        after_reset = self.post_current(self.second, 2)
        self.assertEqual(after_reset['current_track_id'], self.second)

        self.post_json('/api/undo')
        after_undo = self.post_current(self.first, 4)

        self.assertEqual(after_undo['current_track_id'], self.first)
        self.assertEqual(self.get_json('/api/state')['current_track_id'], self.first)

    def test_concurrent_current_posts_ignore_older_selection_tokens(self):
        first_can_continue = threading.Event()
        first_is_waiting = threading.Event()
        original_set_current = standalone_server.ExplorerState.set_current

        def pause_older_post_before_setting_current(state, track_id, selection_token=None):
            if selection_token == 1:
                first_is_waiting.set()
                self.assertTrue(first_can_continue.wait(5), 'newer POST never reached the server')
            return original_set_current(state, track_id, selection_token)

        def post_current(track_id, token):
            body = {'track_id': track_id, 'selection_token': token}
            req = Request(self.base + '/api/current', data=json.dumps(body).encode(), method='POST', headers={'Content-Type': 'application/json'})
            with urlopen(req, timeout=5) as response:
                self.assertEqual(response.status, 200)
                return json.loads(response.read().decode('utf-8'))

        with patch.object(standalone_server.ExplorerState, 'set_current', pause_older_post_before_setting_current):
            older_response = []
            older_thread = threading.Thread(target=lambda: older_response.append(post_current(self.first, 1)))
            older_thread.start()
            self.assertTrue(first_is_waiting.wait(5), 'older POST did not reach the server')

            newer_response = post_current(self.second, 2)
            first_can_continue.set()
            older_thread.join(5)

        self.assertFalse(older_thread.is_alive())
        self.assertEqual(newer_response['current_track_id'], self.second)
        self.assertEqual(older_response[0]['current_track_id'], self.second)
        self.assertEqual(older_response[0]['history'], [None])
        self.assertEqual(self.get_json('/api/state')['current_track_id'], self.second)

    def test_static_assets_are_packaged_and_html_is_not_generated_from_labels(self):
        with urlopen(self.base + '/', timeout=5) as response:
            html = response.read().decode('utf-8')
        self.assertIn('Track Journey Explorer', html)
        self.assertNotIn('First & Friend.flac', html)
        with self.assertRaises(HTTPError) as raised:
            urlopen(self.base + '/../pyproject.toml', timeout=5)
        self.assertEqual(raised.exception.code, 404)


if __name__ == '__main__':
    unittest.main()
