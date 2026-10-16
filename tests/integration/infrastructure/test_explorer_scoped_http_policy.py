"""Real threaded HTTP over each SQLite reader; no error or data stubs."""
from contextlib import closing, contextmanager
import http.client
import json
import sqlite3
import threading
import unittest
from unittest.mock import patch

from music_explorer.frameworks.explorer import server as http_server
from tests.integration.infrastructure.test_explorer_scoped_read_policy import (
    MIRRORS, ScopedFixture, observe_sql,
)

PRIVATE = 'public-private-marker-not-for-errors'
SUMMARY = '/api/track-summaries?limit=100&query=beacon&order=title'


@contextmanager
def endpoint(repo):
    with patch.object(http_server, 'ReadOnlyExplorerSQLiteRepository', return_value=repo):
        server = http_server.create_server(str(repo._path), port=0)
    thread = threading.Thread(target=server.serve_forever, kwargs={'poll_interval': 0.01}, daemon=True)
    thread.start()
    try:
        yield server.server_port
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
        assert not thread.is_alive(), 'Public HTTP thread did not stop'


def request(port, route, data=None):
    with closing(http.client.HTTPConnection('127.0.0.1', port, timeout=5)) as client:
        client.request('GET' if data is None else 'POST', route,
                       body=None if data is None else json.dumps(data),
                       headers={} if data is None else {'Content-Type': 'application/json'})
        response = client.getresponse()
        return response.status, json.loads(response.read())


@contextmanager
def altered(path, table, column, where, parameters, replacement):
    with closing(sqlite3.connect(path)) as db, db:
        original = db.execute(f'SELECT {column} FROM {table} WHERE {where}', parameters).fetchone()[0]
        db.execute(f'UPDATE {table} SET {column}=? WHERE {where}', (replacement, *parameters))
    try:
        yield
    finally:
        with closing(sqlite3.connect(path)) as db, db:
            db.execute(f'UPDATE {table} SET {column}=? WHERE {where}', (original, *parameters))


class ScopedHttpControls(ScopedFixture):
    def test_valid_unknown_ineligible_selection_and_corrected_retry(self):
        for module in MIRRORS:
            with self.subTest(mirror=module.__name__), endpoint(module.ReadOnlyExplorerSQLiteRepository(str(self.path))) as port:
                status, body = request(port, '/api/current', {'track_id': self.handles[0]})
                self.assertEqual(status, 200)
                self.assertEqual(body['current_track_id'], self.handles[0])
                for handle in ('sha256:' + 'f' * 64, 'sha256:' + f'{102:064x}'):
                    self.assertEqual(request(port, '/api/current', {'track_id': handle}),
                                     (400, {'error': 'Unknown explorer track'}))
                    self.assertEqual(request(port, '/api/state')[1], body)
                self.assertEqual(request(port, '/api/current', {'track_id': self.handles[1]})[0], 200)

    def test_consumed_metadata_audio_identity_fail_closed_and_retry_is_request_local(self):
        faults = (
            ('track_metadata', 'common_json', '{', 'Invalid stored metadata'),
            ('track_audio', 'reason', PRIVATE, 'Unexpected analysis database rows'),
            ('tracks', 'size', -1, 'Unexpected analysis database rows'),
        )
        for module in MIRRORS:
            repo = module.ReadOnlyExplorerSQLiteRepository(str(self.path))
            with endpoint(repo) as port:
                for table, column, value, category in faults:
                    key = 'id' if table == 'tracks' else 'track_id'
                    with self.subTest(mirror=module.__name__, fault=column):
                        with altered(self.path, table, column, f'{key}=?', (self.handles[0],), value):
                            self.assertEqual(request(port, SUMMARY), (400, {'error': category}))
                            if table == 'track_metadata':
                                # A different request consumes no malformed metadata.
                                self.assertEqual(request(port, '/api/tracks/' + self.handles[1])[0], 200)
                        self.assertEqual(request(port, SUMMARY)[0], 200)

    def test_selected_malformed_stage_rejects_without_partial_data_then_retry_succeeds(self):
        for module in MIRRORS:
            with endpoint(module.ReadOnlyExplorerSQLiteRepository(str(self.path))) as port:
                route = '/api/tracks/' + self.handles[0]
                self.assertEqual(request(port, route)[0], 200)
                with altered(self.path, 'stages', 'result', 'run_id=? AND stage=?', (self.runs[1], 'bpm'), '{'):
                    status, body = request(port, route)
                    self.assertEqual(status, 400)
                    self.assertEqual(set(body), {'error'})
                    self.assertTrue(body['error'].startswith('Invalid stored stage'))
                    self.assertNotIn(PRIVATE, body['error'])
                self.assertEqual(request(port, route)[0], 200)


class ScopedHttpPolicyRedTests(ScopedFixture):
    def test_http_selection_admission_does_not_enumerate_whole_active_library(self):
        for module in MIRRORS:
            repo = module.ReadOnlyExplorerSQLiteRepository(str(self.path))
            with self.subTest(mirror=module.__name__), endpoint(repo) as port:
                with observe_sql(repo) as sql:
                    status, body = request(port, '/api/current', {'track_id': self.handles[0]})
                self.assertEqual(status, 200)
                self.assertEqual(body['current_track_id'], self.handles[0])
                normalized = [' '.join(s.lower().split()) for s in sql]
                self.assertNotIn('select id from active_tracks order by id', normalized,
                                 'Selection must admit only the requested key, not materialize every active ID')

    def test_selected_http_errors_are_exact_bounded_categories(self):
        for module in MIRRORS:
            repo = module.ReadOnlyExplorerSQLiteRepository(str(self.path))
            with endpoint(repo) as port:
                route = '/api/tracks/' + self.handles[0]
                for fault in ('stage', 'metadata', 'locked'):
                    with self.subTest(mirror=module.__name__, fault=fault):
                        if fault == 'stage':
                            with altered(self.path, 'stages', 'result', 'run_id=? AND stage=?', (self.runs[1], 'bpm'), '{'):
                                response = request(port, route)
                            expected = 'Invalid stored stage'
                        elif fault == 'metadata':
                            with altered(self.path, 'track_metadata', 'warnings_json', 'track_id=?', (self.handles[0],), json.dumps(PRIVATE)):
                                response = request(port, route)
                            expected = 'Invalid stored metadata'
                        else:
                            with closing(sqlite3.connect(self.path)) as lock:
                                self.assertEqual(lock.execute('PRAGMA journal_mode=DELETE').fetchone()[0], 'delete')
                                lock.execute('BEGIN EXCLUSIVE')
                                try:
                                    response = request(port, SUMMARY)
                                finally:
                                    lock.rollback()
                            expected = 'Analysis database error'
                        # Retry is exercised before the intended RED assertion.
                        self.assertEqual(request(port, route)[0], 200)
                        self.assertEqual(response, (400, {'error': expected}))
