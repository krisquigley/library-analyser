"""Bounded public HTTP contract for PR2; only disposable synthetic SQLite data."""
import json
import tempfile
import threading
import unittest
from contextlib import closing
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import urlopen

from music_explorer.frameworks.explorer.server import create_server
from tests.integration.infrastructure.test_explorer_readonly_repository import create_db


class ExplorerSummarySearchContractTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        path = Path(temp.name) / 'synthetic.sqlite'
        # Duplicate folded titles/artists exercise the stable handle tie-break.
        rows = (
            ('Northern Tide', 'Mira', 'eligible'),
            ('northern tide', 'MIRA', 'eligible'),
            ('Northern Beacon', 'Ada', 'eligible'),
            ('Southern Song', 'Mira', 'eligible'),
            ('Northern Tide', 'Mira', 'excluded'),
            (r'folder\mix', 'Other', 'eligible'),
            ('foldermix', 'Other', 'eligible'),
            ('50%_proof', 'Other', 'eligible'),
            ('50XXproof', 'Other', 'eligible'),
        )
        self.handles = ['sha256:' + f'{i:064x}' for i in range(1, len(rows) + 1)]
        with closing(create_db(path)) as db:
            for index, (title, artist, status) in enumerate(rows):
                handle = self.handles[index]
                db.execute('INSERT INTO tracks VALUES(?,?,?)', (handle, handle[7:], 10))
                db.execute('INSERT INTO locations VALUES(?,?,?,?,?)',
                           (f'/synthetic/{index}.flac', handle, 1, 'flac', 1))
                db.execute('INSERT INTO track_metadata VALUES(?,?,?,?)',
                           (handle, json.dumps([['title', title], ['artist', [artist]]]), '[]', '[]'))
                if status == 'excluded':
                    db.execute("UPDATE track_audio SET duration_seconds=1201.0,status='excluded',reason=? WHERE track_id=?",
                               ('duration exceeds 1200.0s; excluded from active library; rescan metadata or choose a shorter file', handle))
            db.commit()
        server = create_server(str(path), host='127.0.0.1', port=0)
        self.addCleanup(server.server_close)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(thread.join, 5)
        self.addCleanup(server.shutdown)
        self.base = f'http://127.0.0.1:{server.server_port}'

    def get_page(self, endpoint='/api/tracks/summary', **params):
        with urlopen(self.base + endpoint + '?' + urlencode(params), timeout=5) as response:
            self.assertEqual(response.status, 200)
            self.assertEqual(response.headers.get_content_type(), 'application/json')
            return json.loads(response.read().decode('utf-8'))

    def assert_handles(self, page, expected):
        self.assertEqual([track['handle'] for track in page['tracks']], expected)

    def test_whitespace_tokens_are_anded_across_title_and_artist(self):
        for query in ('Northern Mira', '  MIRA\tNorthern\n ', 'mira Northern Mira'):
            with self.subTest(query=query):
                page = self.get_page(query=query, limit=2, order='id')
                self.assert_handles(page, self.handles[:2])
                self.assertIsNone(page['next_cursor'])

    def test_nul_token_is_explicitly_rejected_instead_of_silently_matching(self):
        for endpoint, parameter in (('/api/tracks/summary', 'query'),
                                    ('/api/track-summaries', 'q')):
            for query in ('Northern \x00 Mira', '\x00', 'Northern\x00 Mira'):
                with self.subTest(endpoint=endpoint, query=query):
                    with self.assertRaises(HTTPError) as raised:
                        self.get_page(endpoint, **{parameter: query, 'order': 'id'})
                    error = raised.exception
                    self.addCleanup(error.close)
                    self.assertEqual(error.code, 400)
                    self.assertEqual(error.headers.get_content_type(), 'application/json')
                    self.assertEqual(json.loads(error.read().decode('utf-8')),
                                     {'error': 'Explorer summary query must not contain NUL characters'})

    def test_backslash_is_literal_not_a_like_escape(self):
        page = self.get_page(query=r'folder\mix', limit=2, order='id')
        self.assert_handles(page, [self.handles[5]])
        self.assertIsNone(page['next_cursor'])

    def test_percent_and_underscore_are_literal_not_wildcards(self):
        for query in ('%', '_', '%_'):
            with self.subTest(query=query):
                page = self.get_page(query=query, limit=2, order='id')
                self.assert_handles(page, [self.handles[7]])
                self.assertIsNone(page['next_cursor'])

    def test_single_field_casefold_search_and_no_results_remain_supported(self):
        for query, expected in (('tIdE', self.handles[:2]),
                                ('MIRA', [self.handles[i] for i in (0, 1, 3)]),
                                ('not-present', [])):
            with self.subTest(query=query):
                page = self.get_page(query=query, limit=4, order='id')
                self.assert_handles(page, expected)
                self.assertIsNone(page['next_cursor'])

    def test_single_field_pages_are_compact_bounded_and_stable(self):
        for order in ('title', 'artist', 'id'):
            with self.subTest(order=order):
                first = self.get_page(query='tide', limit=1, order=order)
                self.assertEqual(first['limit'], 1)
                self.assert_handles(first, self.handles[:1])
                self.assertTrue(first['next_cursor'])
                second = self.get_page(query='tide', limit=1, order=order, cursor=first['next_cursor'])
                self.assert_handles(second, self.handles[1:2])
                self.assertIsNone(second['next_cursor'])
                self.assertEqual(first, self.get_page(query='tide', limit=1, order=order))
                for page in (first, second):
                    self.assertLessEqual(len(page['tracks']), page['limit'])
                    for track in page['tracks']:
                        for detail_key in ('fields', 'metadata', 'stages', 'candidate_snapshot'):
                            self.assertNotIn(detail_key, track)

    def test_blank_api_compatibility_and_alias_stay_bounded(self):
        expected = [h for i, h in enumerate(self.handles) if i != 4]
        for query in ('', ' \t\n '):
            with self.subTest(query=query):
                page = self.get_page(query=query, limit=100, order='id')
                self.assert_handles(page, expected)
                self.assertEqual(page['limit'], 100)
                self.assertIsNone(page['next_cursor'])
        self.assertEqual(self.get_page(query='tide', limit=1, order='id'),
                         self.get_page('/api/track-summaries', q='tide', limit=1, order='id'))

    def test_invalid_query_order_cursor_and_page_bounds_are_bad_requests(self):
        invalid = ({'query': 'x' * 201}, {'order': 'random'}, {'cursor': 'not-a-cursor'},
                   {'limit': 0}, {'limit': 101}, {'limit': 'all'})
        for params in invalid:
            with self.subTest(params=params):
                with self.assertRaises(HTTPError) as raised:
                    self.get_page(**params)
                error = raised.exception
                self.addCleanup(error.close)
                self.assertEqual(error.code, 400)
                self.assertEqual(error.headers.get_content_type(), 'application/json')
                self.assertIn('error', json.loads(error.read().decode('utf-8')))


if __name__ == '__main__':
    unittest.main()
