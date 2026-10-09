import json
import os
import sqlite3
import tempfile
import threading
import time
import unittest
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import urlopen

from music_analyzer.frameworks.explorer.server import create_server

APP_ID = 0x4D414E41


def create_synthetic_explorer_db(path: Path, track_count: int) -> None:
    """Create a public-safe synthetic explorer database.

    The rows intentionally use generated identifiers and generated location
    strings only.  No user database, Mixxx library, or audio files are read.
    """
    db = sqlite3.connect(path)
    db.execute('PRAGMA journal_mode=OFF')
    db.execute('PRAGMA synchronous=OFF')
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
    db.execute(f'PRAGMA application_id={APP_ID}')
    db.execute('PRAGMA user_version=6')
    tracks = []
    locations = []
    roots = []
    audio = []
    metadata = []
    for index in range(track_count):
        sha = f'{index + 1:064x}'
        track_id = f'sha256:{sha}'
        title = f'Track {index:05d}'
        artist = f'Synthetic Artist {index % 37:02d}'
        location = f'/synthetic-library/{artist}/{title}.flac'
        tracks.append((track_id, sha, 123456 + index))
        locations.append((location, track_id, 1_700_000_000_000_000_000 + index, 'flac', 1))
        roots.append(('/synthetic-library', location))
        audio.append((track_id, 180.0, 'mutagen', 'eligible', ''))
        metadata.append((
            track_id,
            json.dumps([['title', title], ['artist', artist]], separators=(',', ':')),
            json.dumps([], separators=(',', ':')),
            json.dumps([], separators=(',', ':')),
        ))
    db.executemany('INSERT INTO tracks VALUES(?,?,?)', tracks)
    db.executemany('INSERT INTO locations VALUES(?,?,?,?,?)', locations)
    db.executemany('INSERT INTO scan_roots VALUES(?,?)', roots)
    db.executemany('INSERT INTO track_audio VALUES(?,?,?,?,?)', audio)
    db.executemany('INSERT INTO track_metadata VALUES(?,?,?,?)', metadata)
    db.commit()
    db.close()


class ExplorerStartupPerformanceAcceptanceTests(unittest.TestCase):
    def serve_synthetic_library(self, track_count):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        db_path = Path(temp.name) / 'synthetic-analysis.sqlite'
        create_synthetic_explorer_db(db_path, track_count)
        server = create_server(str(db_path), host='127.0.0.1', port=0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.shutdown)
        self.addCleanup(server.server_close)
        return f'http://127.0.0.1:{server.server_port}'

    def get_json_bytes(self, base, path, query):
        started = time.perf_counter()
        with urlopen(base + path + '?' + urlencode(query), timeout=10) as response:
            self.assertEqual(response.headers.get_content_type(), 'application/json')
            payload = response.read()
        return json.loads(payload.decode('utf-8')), len(payload), time.perf_counter() - started

    def assert_summary_page_contract(self, page, expected_total):
        self.assertEqual(page['metadata']['track_count'], expected_total)
        self.assertEqual(page['limit'], 100)
        self.assertEqual(len(page['tracks']), 100)
        self.assertIn('next_cursor', page)
        first = page['tracks'][0]
        self.assertEqual(set(first), {'handle', 'title', 'artist', 'display_label', 'available_locations'})
        self.assertTrue(first['handle'].startswith('sha256:'))
        self.assertEqual(first['title'], 'Track 00000')
        self.assertEqual(first['artist'], 'Synthetic Artist 00')

    def test_summary_api_has_bounded_payload_for_5k_and_20k_cold_and_warm_requests(self):
        """Synthetic benchmark contract: compact first page, not full-library JSON.

        The thresholds are intentionally about product safety, not machine speed:
        every 100-row page must stay comfortably under the public 150 KiB target
        for both cold and warm requests on 5k and 20k generated libraries.
        """
        for track_count in (5_000, 20_000):
            with self.subTest(track_count=track_count):
                base = self.serve_synthetic_library(track_count)
                query = {'limit': '100', 'order': 'title'}
                cold_page, cold_bytes, cold_seconds = self.get_json_bytes(base, '/api/tracks/summary', query)
                warm_page, warm_bytes, warm_seconds = self.get_json_bytes(base, '/api/tracks/summary', query)

                self.assert_summary_page_contract(cold_page, track_count)
                self.assert_summary_page_contract(warm_page, track_count)
                self.assertLessEqual(cold_bytes, 150 * 1024)
                self.assertLessEqual(warm_bytes, 150 * 1024)
                self.assertLess(cold_seconds, 10.0)
                self.assertLess(warm_seconds, 10.0)

    @unittest.skipUnless(os.environ.get('RUN_BROWSER_SMOKE') == '1', 'opt-in Playwright Chromium first-view benchmark')
    def test_browser_reaches_first_usable_track_list_before_graph_response(self):
        from playwright.sync_api import sync_playwright
        import music_explorer.frameworks.explorer.server as standalone_server
        from unittest.mock import patch

        base = self.serve_synthetic_library(5_000)
        graph_started = threading.Event()
        release_graph = threading.Event()
        original_execute = standalone_server.BuildMoodAxisGraph.execute

        def delayed_graph(use_case, *args, **kwargs):
            graph_started.set()
            release_graph.wait(5)
            return original_execute(use_case, *args, **kwargs)

        with patch.object(standalone_server.BuildMoodAxisGraph, 'execute', delayed_graph):
            with sync_playwright() as p:
                browser = p.chromium.launch(channel='chromium')
                page = browser.new_page()
                try:
                    page.goto(base + '/', wait_until='domcontentloaded')
                    page.get_by_role('searchbox', name='Search tracks by title or artist').wait_for(timeout=1500)
                    self.assertEqual(page.locator('#tracks tbody tr').count(), 0)
                    search = page.get_by_role('searchbox', name='Search tracks by title or artist')
                    self.assertEqual(search.count(), 1)
                    started = time.perf_counter()
                    search.fill('Track 00099')
                    page.get_by_role('button', name='Track 00099').wait_for(timeout=1000)
                    self.assertLess(time.perf_counter() - started, 1.0)
                    self.assertTrue(graph_started.wait(5), 'startup automatically requests graph without a manual click')
                finally:
                    release_graph.set()
                    browser.close()


if __name__ == '__main__':
    unittest.main()
