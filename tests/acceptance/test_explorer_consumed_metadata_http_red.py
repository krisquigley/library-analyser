"""Issue88 P6: canonical/alias summary HTTP is all-or-error, not fallback."""
import json
import sqlite3
from contextlib import closing
from concurrent.futures import ThreadPoolExecutor
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import urlopen

from music_explorer.frameworks.explorer.server import create_server
from tests.integration.infrastructure.test_explorer_consumed_metadata_red import (
    PRIVATE_MARKER, corrupt_common, create_public_fixture, stored_snapshot,
)


class ExplorerConsumedMetadataHTTPTests(unittest.TestCase):
    server_factory = staticmethod(create_server)
    routes = (('/api/tracks/summary', 'query'), ('/api/track-summaries', 'q'))

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / 'public.sqlite'
        self.handles = create_public_fixture(self.path)
        server = self.server_factory(str(self.path), host='127.0.0.1', port=0)
        self.addCleanup(server.server_close)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(thread.join, 5)
        self.addCleanup(server.shutdown)
        self.base = f'http://127.0.0.1:{server.server_port}'

    def request(self, route, **params):
        return urlopen(self.base + route + '?' + urlencode(params), timeout=5)

    def assert_sanitized_failure(self, route, **params):
        before = stored_snapshot(self.path)
        with self.assertRaises(HTTPError) as raised:
            with self.request(route, **params) as response:
                # Consume/close even the current misleading successful page.
                response.read()
        with raised.exception as response:
            self.assertEqual(response.code, 400)
            self.assertEqual(response.headers.get_content_type(), 'application/json')
            body = response.read().decode('utf-8')
        self.assertEqual(json.loads(body), {'error': 'Invalid stored metadata'})
        for private in (PRIVATE_MARKER, str(self.path), self.handles[3], 'Bad', 'common_json',
                        'user-defined function', 'too many values to unpack'):
            self.assertNotIn(private, body)
        # Exact error-only JSON prohibits partial count/tracks/cursor delivery.
        self.assertEqual(stored_snapshot(self.path), before)

    def test_sort_consumed_unreturned_metadata_fails_on_canonical_and_alias(self):
        corrupt_common(self.path, self.handles[3])
        for route, _parameter in self.routes:
            for order in ('title', 'artist'):
                with self.subTest(route=route, order=order):
                    self.assert_sanitized_failure(route, limit=1, order=order)

    def test_query_consumed_nonmatching_metadata_fails_on_canonical_and_alias(self):
        corrupt_common(self.path, self.handles[3])
        for route, parameter in self.routes:
            with self.subTest(route=route):
                self.assert_sanitized_failure(route, **{parameter: 'beacon', 'limit': 1, 'order': 'id'})

    def test_selected_metadata_error_is_sanitized_on_both_routes(self):
        corrupt_common(self.path, self.handles[0])
        for route, _parameter in self.routes:
            with self.subTest(route=route):
                self.assert_sanitized_failure(route, limit=1, order='id')

    def test_late_evaluated_tags_error_is_sanitized_on_both_routes(self):
        with closing(sqlite3.connect(self.path)) as db:
            db.execute('UPDATE track_metadata SET tags_json=? WHERE track_id=?', ('{}', self.handles[3]))
            db.commit()
        for route, parameter in self.routes:
            with self.subTest(route=route):
                self.assert_sanitized_failure(route, limit=1, order='artist')
                self.assert_sanitized_failure(route, **{parameter: 'beacon', 'limit': 1, 'order': 'id'})

    def test_raw_types_and_nested_json_are_sanitized(self):
        cases = (
            ('common_json', json.dumps([['title', None]])),
            ('common_json', json.dumps([['title', {'private': PRIVATE_MARKER}]])),
            ('common_json', json.dumps([[None, 'title']])),
            ('common_json', json.dumps([['title', True]])),
            ('common_json', json.dumps([['title', [12]]])),
            ('tags_json', json.dumps([['title', PRIVATE_MARKER]])),
            ('tags_json', json.dumps([['title', [12]]])),
            ('tags_json', json.dumps([['title', None]])),
            ('tags_json', json.dumps([['title', [False, {'private': PRIVATE_MARKER}]]])),
            ('tags_json', json.dumps([[12, ['title']]])),
            ('common_json', '[' * 10000 + '0' + ']' * 10000),
        )
        self.assertEqual(len(cases[-1][1]), 20001)
        for column, payload in cases:
            for index in (0, 3):
                with closing(sqlite3.connect(self.path)) as db:
                    original = db.execute(f'SELECT {column} FROM track_metadata WHERE track_id=?', (self.handles[index],)).fetchone()[0]
                    db.execute(f'UPDATE track_metadata SET {column}=? WHERE track_id=?', (payload, self.handles[index]))
                    db.commit()
                try:
                    for route, parameter in self.routes:
                        with self.subTest(column=column, index=index, route=route, payload=payload[:60]):
                            self.assert_sanitized_failure(route, limit=1, order='id' if index == 0 else 'title')
                            if index == 3:
                                self.assert_sanitized_failure(route, **{parameter: 'beacon', 'limit': 1, 'order': 'id'})
                finally:
                    with closing(sqlite3.connect(self.path)) as db:
                        db.execute(f'UPDATE track_metadata SET {column}=? WHERE track_id=?', (original, self.handles[index]))
                        db.commit()

    def test_concurrent_decoder_failure_does_not_poison_valid_requests(self):
        corrupt_common(self.path, self.handles[3], '[' * 10000 + '0' + ']' * 10000)
        before = stored_snapshot(self.path)

        def request_page(route, order):
            try:
                with self.request(route, limit=1, order=order) as response:
                    return response.status, json.loads(response.read())
            except HTTPError as error:
                with error:
                    return error.code, json.loads(error.read())

        with ThreadPoolExecutor(max_workers=6) as pool:
            jobs = [(order, pool.submit(request_page, route, order))
                    for route, _parameter in self.routes for order in ('title', 'id', 'title')]
            for order, future in jobs:
                status, body = future.result(timeout=5)
                if order == 'title':
                    self.assertEqual((status, body), (400, {'error': 'Invalid stored metadata'}))
                else:
                    self.assertEqual(status, 200)
                    self.assertEqual(body['metadata']['track_count'], 4)
                    self.assertEqual(body['tracks'][0]['handle'], self.handles[0])
                    self.assertTrue(body['next_cursor'])
        self.assertEqual(stored_snapshot(self.path), before)

    def test_valid_alias_counts_order_cursor_and_unrelated_page_are_preserved(self):
        before = stored_snapshot(self.path)
        for order in ('title', 'artist', 'id'):
            with self.subTest(order=order):
                pages = []
                for route, parameter in self.routes:
                    cursor, handles, sequence = None, [], []
                    for number in range(4):
                        with self.request(route, **{parameter: 'beacon', 'limit': 1,
                                                   'order': order, **({'cursor': cursor} if cursor else {})}) as response:
                            self.assertEqual(response.status, 200)
                            self.assertEqual(response.headers.get_content_type(), 'application/json')
                            page = json.loads(response.read().decode('utf-8'))
                        self.assertEqual(page['limit'], 1)
                        self.assertEqual(page['metadata']['track_count'], 4)
                        handles.extend(track['handle'] for track in page['tracks'])
                        cursor = page['next_cursor']
                        self.assertEqual(bool(cursor), number < 3)
                        sequence.append(page)
                    self.assertEqual(handles, list(self.handles))
                    pages.append(sequence)
                self.assertEqual(pages[0], pages[1])
        self.assertEqual(stored_snapshot(self.path), before)
        corrupt_common(self.path, self.handles[3])
        before = stored_snapshot(self.path)
        for route, _parameter in self.routes:
            with self.request(route, limit=1, order='id') as response:
                self.assertEqual(response.status, 200)
                page = json.loads(response.read().decode('utf-8'))
            self.assertEqual([track['handle'] for track in page['tracks']], list(self.handles[:1]))
            self.assertTrue(page['next_cursor'])
        self.assertEqual(stored_snapshot(self.path), before)


class AnalyzerConsumedMetadataHTTPTests(ExplorerConsumedMetadataHTTPTests):
    from music_analyzer.frameworks.explorer.server import create_server as analyzer_server
    server_factory = staticmethod(analyzer_server)


if __name__ == '__main__':
    unittest.main()
