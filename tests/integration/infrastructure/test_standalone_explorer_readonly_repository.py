import json
import os
import resource
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from music_analyzer.application.dto.analysis import AudioSource, StageResult
from music_analyzer.application.dto.catalogue import Inventory, ScannedFile, TrackMetadata as AnalyzerTrackMetadata
from music_analyzer.domain.analysis import ScoreSummary
from music_analyzer.domain.catalogue import FileIdentity
from music_analyzer.infrastructure.persistence.analysis import SQLiteAnalysisRepository
import music_explorer.infrastructure.explorer_readonly as standalone_explorer_readonly_module
from music_explorer.infrastructure.explorer_readonly import AnalysisError, ReadOnlyExplorerSQLiteRepository

APP_ID = 0x4D414E41
_MEMORY_LIMIT_BYTES = 128 * 1024 * 1024
_OVERSIZED_STAGE_BYTES = 24 * 1024 * 1024
_TIMEOUT_SECONDS = 15


def _register_graph_track(repository, suffix, location):
    identity = FileIdentity(suffix * 64, 123)
    repository.register(Inventory('/music', (
        ScannedFile(location, identity, 1, 'flac', AnalyzerTrackMetadata(duration_seconds=180.0, duration_source='mutagen')),
    ), (), True))
    return identity


def _complete_graph_feature_run(repository, identity, location):
    run_id = repository.start(AudioSource(location, identity.track_id))
    for stage in (
        StageResult('bpm', (('algorithm', 'test-bpm'),), 'steady', (('bpm', 124.0),)),
        StageResult('key', (('algorithm', 'test-key'),), 'classified', (('key', '8A'), ('scale', 'minor'), ('strength', 0.731), ('coverage', 1.0))),
        StageResult('genres', (('algorithm', 'test-genre'),), 'labels', (('genre', 'house'), ('genre', 'deep house'))),
        StageResult('mood', (('algorithm', 'test-mood'),), 'scores', summary=ScoreSummary(('happy', 'dark'), (0.75, 0.20), (0.70, 0.10), (0.80, 0.30), 1.0)),
        StageResult('energy', (('algorithm', 'test-energy'),), 'score', summary=ScoreSummary(('energy',), (0.66,), (0.60,), (0.70,), 1.0)),
    ):
        repository.save_stage(run_id, stage)
    repository.finish(run_id, 'completed', '')
    return run_id


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
    CREATE TABLE track_metadata(track_id TEXT PRIMARY KEY REFERENCES tracks(id), common_json TEXT NOT NULL, tags_json TEXT NOT NULL, warnings_json TEXT NOT NULL);
CREATE TABLE track_audio(track_id TEXT PRIMARY KEY REFERENCES tracks(id), duration_seconds REAL, duration_source TEXT NOT NULL, status TEXT NOT NULL CHECK(status IN ('eligible','excluded','unknown')), reason TEXT NOT NULL);
CREATE VIEW active_tracks AS SELECT t.id,t.sha256,t.size FROM tracks t JOIN track_audio a ON a.track_id=t.id WHERE a.status='eligible';
CREATE VIEW active_locations AS SELECT l.path,l.track_id,l.mtime_ns,l.format,l.available FROM locations l JOIN track_audio a ON a.track_id=l.track_id WHERE l.available=1 AND a.status='eligible';
''')
    db.execute(f'PRAGMA application_id={APP_ID}')
    db.execute('PRAGMA user_version=6')
    return db


class StandaloneReadOnlyExplorerSQLiteRepositoryTests(unittest.TestCase):
    def test_rejects_missing_track_audio_row_for_each_track(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'analysis.sqlite'
            db = create_db(path)
            tid = 'sha256:' + '8' * 64
            db.execute('INSERT INTO tracks VALUES(?,?,?)', (tid, '8' * 64, 10))
            db.commit(); db.close()

            with self.assertRaisesRegex(AnalysisError, 'Unexpected analysis database rows'):
                ReadOnlyExplorerSQLiteRepository(str(path)).track_ids()

    def test_rejects_orphan_track_audio_row_inserted_with_foreign_keys_disabled_before_showing_results(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'analysis.sqlite'
            db = create_db(path)
            db.execute('PRAGMA foreign_keys=OFF')
            good_tid = 'sha256:' + '8' * 64
            db.execute('INSERT INTO tracks VALUES(?,?,?)', (good_tid, '8' * 64, 10))
            db.execute('INSERT INTO track_audio VALUES(?,?,?,?,?)', (good_tid, 120.0, 'mutagen', 'eligible', ''))
            db.execute(
                'INSERT INTO track_audio VALUES(?,?,?,?,?)',
                ('sha256:' + '9' * 64, 120.0, 'mutagen', 'eligible', ''),
            )
            db.commit(); db.close()

            with self.assertRaisesRegex(AnalysisError, 'Unexpected analysis database rows'):
                ReadOnlyExplorerSQLiteRepository(str(path)).track_ids()

    def test_accepts_normalized_trusted_nonfinite_duration_as_unknown(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'analysis.sqlite'
            db = create_db(path)
            tid = 'sha256:' + '7' * 64
            db.execute('INSERT INTO tracks VALUES(?,?,?)', (tid, '7' * 64, 10))
            db.execute('INSERT INTO track_audio VALUES(?,?,?,?,?)', (
                tid,
                None,
                'mutagen',
                'unknown',
                'duration unverified; excluded from active library until mutagen/ffprobe verifies duration; rescan audio metadata',
            ))
            db.commit(); db.close()

            repo = ReadOnlyExplorerSQLiteRepository(str(path))
            self.assertEqual(repo.track_ids(), ())
            self.assertIsNone(repo.read_track(tid).metadata.duration_seconds)

    def test_rejects_tampered_track_audio_rows_instead_of_trusting_active_view_status(self):
        for audio_update in (
            (119.0, '', 'eligible', ''),
            (120.0, 'mutagen', 'archived', ''),
            (None, 'mutagen', 'excluded', 'duration invalid; excluded from active library until mutagen/ffprobe verifies a positive finite duration; rescan audio metadata'),
            (float('inf'), 'mutagen', 'excluded', 'duration invalid; excluded from active library until mutagen/ffprobe verifies a positive finite duration; rescan audio metadata'),
        ):
            with self.subTest(audio_update=audio_update), tempfile.TemporaryDirectory() as td:
                path = Path(td) / 'analysis.sqlite'
                db = create_db(path)
                db.execute('PRAGMA ignore_check_constraints=ON')
                tid = 'sha256:' + '9' * 64
                db.execute('INSERT INTO tracks VALUES(?,?,?)', (tid, '9' * 64, 10))
                db.execute('INSERT INTO track_audio VALUES(?,?,?,?,?)', (tid, *audio_update))
                db.commit(); db.close()

                with self.assertRaisesRegex(AnalysisError, 'Unexpected analysis database rows'):
                    ReadOnlyExplorerSQLiteRepository(str(path)).track_ids()

    def test_rejects_v6_schema_with_loose_active_view_definition(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'analysis.sqlite'
            db = create_db(path)
            db.execute('DROP VIEW active_tracks')
            db.execute('CREATE VIEW active_tracks AS SELECT id,sha256,size FROM tracks')
            db.commit(); db.close()
            with self.assertRaisesRegex(AnalysisError, 'Unexpected analysis database schema'):
                ReadOnlyExplorerSQLiteRepository(str(path)).track_ids()

    def test_rejects_malformed_stage_summary_with_empty_labels_and_zero_coverage(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'analysis.sqlite'
            db = create_db(path)
            tid = 'sha256:' + 'b' * 64
            db.execute('INSERT INTO tracks VALUES(?,?,?)', (tid, 'b' * 64, 10))
            db.execute('INSERT INTO track_audio VALUES(?,?,?,?,?)', (tid, 120.0, 'mutagen', 'eligible', ''))
            db.execute('INSERT INTO runs(id,location,status,detail) VALUES(?,?,?,?)', ('run', '', 'completed', ''))
            db.execute('INSERT INTO run_tracks VALUES(?,?)', ('run', tid))
            payload = {
                'stage': 'energy',
                'provenance': [],
                'uncertainty': '',
                'values': [],
                'summary': {'labels': [], 'mean': [], 'minimum': [], 'maximum': [], 'coverage': 0},
            }
            db.execute('INSERT INTO stages VALUES(?,?,?)', ('run', 'energy', json.dumps(payload)))
            db.commit(); db.close()
            with self.assertRaisesRegex(AnalysisError, 'Invalid stored stage'):
                ReadOnlyExplorerSQLiteRepository(str(path)).read_track(tid)

    def test_rejects_boolean_stage_summary_numbers(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'analysis.sqlite'
            db = create_db(path)
            tid = 'sha256:' + 'b' * 64
            db.execute('INSERT INTO tracks VALUES(?,?,?)', (tid, 'b' * 64, 10))
            db.execute('INSERT INTO track_audio VALUES(?,?,?,?,?)', (tid, 120.0, 'mutagen', 'eligible', ''))
            db.execute('INSERT INTO runs(id,location,status,detail) VALUES(?,?,?,?)', ('run', '', 'completed', ''))
            db.execute('INSERT INTO run_tracks VALUES(?,?)', ('run', tid))
            payload = {
                'stage': 'mood',
                'provenance': [],
                'uncertainty': '',
                'values': [['valence', True]],
                'summary': {
                    'labels': ['valence'],
                    'mean': [True],
                    'minimum': [0.0],
                    'maximum': [1.0],
                    'coverage': 1.0,
                },
            }
            db.execute('INSERT INTO stages VALUES(?,?,?)', ('run', 'mood', json.dumps(payload)))
            db.commit(); db.close()
            with self.assertRaisesRegex(AnalysisError, 'Invalid stored stage'):
                ReadOnlyExplorerSQLiteRepository(str(path)).read_track(tid)

    def test_rejects_boolean_stage_summary_coverage(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'analysis.sqlite'
            db = create_db(path)
            tid = 'sha256:' + 'b' * 64
            db.execute('INSERT INTO tracks VALUES(?,?,?)', (tid, 'b' * 64, 10))
            db.execute('INSERT INTO track_audio VALUES(?,?,?,?,?)', (tid, 120.0, 'mutagen', 'eligible', ''))
            db.execute('INSERT INTO runs(id,location,status,detail) VALUES(?,?,?,?)', ('run', '', 'completed', ''))
            db.execute('INSERT INTO run_tracks VALUES(?,?)', ('run', tid))
            payload = {
                'stage': 'mood',
                'provenance': [],
                'uncertainty': '',
                'values': [['valence', 0.5]],
                'summary': {
                    'labels': ['valence'],
                    'mean': [0.5],
                    'minimum': [0.0],
                    'maximum': [1.0],
                    'coverage': True,
                },
            }
            db.execute('INSERT INTO stages VALUES(?,?,?)', ('run', 'mood', json.dumps(payload)))
            db.commit(); db.close()
            with self.assertRaisesRegex(AnalysisError, 'Invalid stored stage'):
                ReadOnlyExplorerSQLiteRepository(str(path)).read_track(tid)

    def test_list_track_summaries_is_compact_paginated_and_does_not_read_stage_results(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'analysis.sqlite'
            db = create_db(path)
            first = 'sha256:' + '1' * 64
            second = 'sha256:' + '2' * 64
            for tid, label in ((first, 'First.flac'), (second, 'Second.flac')):
                db.execute('INSERT INTO tracks VALUES(?,?,?)', (tid, tid.split(':')[1], 10))
                db.execute('INSERT INTO locations VALUES(?,?,?,?,?)', ('/private/music/' + label, tid, 1, 'flac', 1))
                db.execute('INSERT INTO track_audio VALUES(?,?,?,?,?)', (tid, 120.0, 'mutagen', 'eligible', ''))
                db.execute('INSERT INTO track_metadata VALUES(?,?,?,?)', (tid, '[["title", "' + label[:-5] + '"]]', '[]', '[]'))
            db.execute('INSERT INTO runs(id,location,status,detail) VALUES(?,?,?,?)', ('run-1', '/private/music/First.flac', 'completed', ''))
            db.execute('INSERT INTO run_tracks VALUES(?,?)', ('run-1', first))
            db.execute('INSERT INTO stages VALUES(?,?,?)', ('run-1', 'bpm', 'not-json-summary-endpoint-must-not-read-this'))
            db.commit(); db.close()

            repo = ReadOnlyExplorerSQLiteRepository(str(path))
            metadata, count, page, cursor = repo.list_track_summaries(1, query='first', order='title')

            self.assertEqual(metadata['read_policy'], 'bounded_read_transaction')
            self.assertEqual(count, 1)
            self.assertEqual(page[0].handle, first)
            self.assertEqual(page[0].title, 'First')
            self.assertIsNone(cursor)
            _metadata, count, first_page, cursor = repo.list_track_summaries(1, order='id')
            self.assertEqual(count, 2)
            self.assertEqual(tuple(row.handle for row in first_page), (first,))
            _metadata, _count, second_page, _cursor = repo.list_track_summaries(1, cursor=cursor, order='id')
            self.assertEqual(tuple(row.handle for row in second_page), (second,))

    def test_list_track_summaries_orders_title_and_artist_by_returned_metadata_with_stable_cursors(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'analysis.sqlite'
            db = create_db(path)
            rows = (
                ('sha256:' + '1' * 64, 'Gamma Filename.flac', '[]', '[["artist", ["Zulu"]]]'),
                ('sha256:' + '2' * 64, 'Zulu Filename.flac', '[["title", "Alpha Title"], ["artist", ["Bravo"]]]', '[]'),
                ('sha256:' + '3' * 64, 'Beta Filename.flac', '[["title", "Middle Title"], ["artist", ["Alpha"]]]', '[]'),
            )
            for tid, label, common_json, tags_json in rows:
                db.execute('INSERT INTO tracks VALUES(?,?,?)', (tid, tid.split(':')[1], 10))
                db.execute('INSERT INTO locations VALUES(?,?,?,?,?)', ('/private/music/' + label, tid, 1, 'flac', 1))
                db.execute('INSERT INTO track_audio VALUES(?,?,?,?,?)', (tid, 120.0, 'mutagen', 'eligible', ''))
                db.execute('INSERT INTO track_metadata VALUES(?,?,?,?)', (tid, common_json, tags_json, '[]'))
            db.execute('INSERT INTO runs(id,location,status,detail) VALUES(?,?,?,?)', ('run-1', '/private/music/01-filename.flac', 'completed', ''))
            db.execute('INSERT INTO run_tracks VALUES(?,?)', ('run-1', rows[0][0]))
            db.execute('INSERT INTO stages VALUES(?,?,?)', ('run-1', 'bpm', 'not-json-summary-endpoint-must-not-read-this'))
            db.commit(); db.close()

            repo = ReadOnlyExplorerSQLiteRepository(str(path))

            _metadata, count, title_page_1, title_cursor = repo.list_track_summaries(2, order='title')
            self.assertEqual(count, 3)
            self.assertEqual(tuple(row.title for row in title_page_1), ('Alpha Title', 'Gamma Filename.flac'))
            _metadata, count, title_page_2, title_cursor_2 = repo.list_track_summaries(2, cursor=title_cursor, order='title')
            self.assertEqual(count, 3)
            self.assertEqual(tuple(row.title for row in title_page_2), ('Middle Title',))
            self.assertIsNone(title_cursor_2)

            _metadata, count, artist_page_1, artist_cursor = repo.list_track_summaries(2, order='artist')
            self.assertEqual(count, 3)
            self.assertEqual(tuple(row.artist for row in artist_page_1), ('Alpha', 'Bravo'))
            _metadata, count, artist_page_2, artist_cursor_2 = repo.list_track_summaries(2, cursor=artist_cursor, order='artist')
            self.assertEqual(count, 3)
            self.assertEqual(tuple(row.artist for row in artist_page_2), ('Zulu',))
            self.assertIsNone(artist_cursor_2)


    def test_list_track_summaries_keeps_total_count_while_following_cursors(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'analysis.sqlite'
            db = create_db(path)
            rows = []
            for idx in range(250):
                hex_id = f'{idx + 1:064x}'
                tid = 'sha256:' + hex_id
                if idx < 150:
                    title = f'Needle Title {idx:03d}'
                    artist = f'Needle Artist {idx:03d}'
                else:
                    title = f'Other Title {idx:03d}'
                    artist = f'Other Artist {idx:03d}'
                rows.append((tid, title, artist))
                db.execute('INSERT INTO tracks VALUES(?,?,?)', (tid, hex_id, idx + 10))
                db.execute('INSERT INTO locations VALUES(?,?,?,?,?)', (f'/private/music/{idx:03d}.flac', tid, idx, 'flac', 1))
                db.execute('INSERT INTO track_audio VALUES(?,?,?,?,?)', (tid, 120.0, 'mutagen', 'eligible', ''))
                db.execute('INSERT INTO track_metadata VALUES(?,?,?,?)', (
                    tid,
                    '[[' + json.dumps('title') + ', ' + json.dumps(title) + '], [' + json.dumps('artist') + ', [' + json.dumps(artist) + ']]]',
                    '[]',
                    '[]',
                ))
            db.commit(); db.close()

            repo = ReadOnlyExplorerSQLiteRepository(str(path))

            for order in ('title', 'artist'):
                with self.subTest(order=order, query=''):
                    cursor = None
                    handles = []
                    counts = []
                    page_lengths = []
                    for _ in range(3):
                        _metadata, count, page, cursor = repo.list_track_summaries(100, cursor=cursor, order=order)
                        counts.append(count)
                        page_lengths.append(len(page))
                        handles.extend(row.handle for row in page)
                    self.assertEqual(counts, [250, 250, 250])
                    self.assertEqual(page_lengths, [100, 100, 50])
                    self.assertIsNone(cursor)
                    expected = tuple(tid for tid, _title, _artist in sorted(
                        rows,
                        key=(lambda row: (row[1].casefold(), row[0])) if order == 'title' else (lambda row: (row[2].casefold(), row[0])),
                    ))
                    self.assertEqual(tuple(handles), expected)

                with self.subTest(order=order, query='needle'):
                    cursor = None
                    handles = []
                    counts = []
                    page_lengths = []
                    for _ in range(3):
                        _metadata, count, page, cursor = repo.list_track_summaries(50, cursor=cursor, query='needle', order=order)
                        counts.append(count)
                        page_lengths.append(len(page))
                        handles.extend(row.handle for row in page)
                    self.assertEqual(counts, [150, 150, 150])
                    self.assertEqual(page_lengths, [50, 50, 50])
                    self.assertIsNone(cursor)
                    matching_rows = rows[:150]
                    expected = tuple(tid for tid, _title, _artist in sorted(
                        matching_rows,
                        key=(lambda row: (row[1].casefold(), row[0])) if order == 'title' else (lambda row: (row[2].casefold(), row[0])),
                    ))
                    self.assertEqual(tuple(handles), expected)


    def test_list_track_summaries_unicode_cursor_uses_same_fold_as_sql_order(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'analysis.sqlite'
            db = create_db(path)
            rows = (
                ('sha256:' + '1' * 64, 'First.flac', 'Älpha Artist'),
                ('sha256:' + '2' * 64, 'Second.flac', 'Ålpha Artist'),
            )
            for tid, label, artist in rows:
                db.execute('INSERT INTO tracks VALUES(?,?,?)', (tid, tid.split(':')[1], 10))
                db.execute('INSERT INTO locations VALUES(?,?,?,?,?)', ('/private/music/' + label, tid, 1, 'flac', 1))
                db.execute('INSERT INTO track_audio VALUES(?,?,?,?,?)', (tid, 120.0, 'mutagen', 'eligible', ''))
                db.execute('INSERT INTO track_metadata VALUES(?,?,?,?)', (tid, '[[' + json.dumps('title') + ', ' + json.dumps(label[:-5]) + ']]', '[[' + json.dumps('artist') + ', [' + json.dumps(artist) + ']]]', '[]'))
            db.execute('INSERT INTO runs(id,location,status,detail) VALUES(?,?,?,?)', ('run-1', '/private/music/First.flac', 'completed', ''))
            db.execute('INSERT INTO run_tracks VALUES(?,?)', ('run-1', rows[0][0]))
            db.execute('INSERT INTO stages VALUES(?,?,?)', ('run-1', 'bpm', 'not-json-summary-endpoint-must-not-read-this'))
            db.commit(); db.close()

            repo = ReadOnlyExplorerSQLiteRepository(str(path))

            _metadata, count, first_page, cursor = repo.list_track_summaries(1, order='artist')
            self.assertEqual(count, 2)
            self.assertEqual(tuple(row.artist for row in first_page), ('Älpha Artist',))
            self.assertIsNotNone(cursor)
            _metadata, count, second_page, second_cursor = repo.list_track_summaries(1, cursor=cursor, order='artist')
            self.assertEqual(count, 2)
            self.assertEqual(tuple(row.artist for row in second_page), ('Ålpha Artist',))
            self.assertIsNone(second_cursor)

    def test_list_track_summaries_searches_visible_title_and_artist_only(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'analysis.sqlite'
            db = create_db(path)
            rows = (
                ('sha256:' + '1' * 64, 'FalsePositive.flac', '[[' + json.dumps('album_artist') + ', ' + json.dumps('Private Notes') + ']]', '[]'),
                ('sha256:' + '2' * 64, 'Legitimate.flac', '[[' + json.dumps('title') + ', ' + json.dumps('Quiet Song') + '], [' + json.dumps('artist') + ', [' + json.dumps('Visible Artist') + ']]]', '[]'),
                ('sha256:' + '3' * 64, 'Case.flac', '[[' + json.dumps('title') + ', ' + json.dumps('MiXeD Case Title') + ']]', '[]'),
            )
            for tid, label, common_json, tags_json in rows:
                db.execute('INSERT INTO tracks VALUES(?,?,?)', (tid, tid.split(':')[1], 10))
                db.execute('INSERT INTO locations VALUES(?,?,?,?,?)', ('/private/music/' + label, tid, 1, 'flac', 1))
                db.execute('INSERT INTO track_audio VALUES(?,?,?,?,?)', (tid, 120.0, 'mutagen', 'eligible', ''))
                db.execute('INSERT INTO track_metadata VALUES(?,?,?,?)', (tid, common_json, tags_json, '[]'))
            db.execute('INSERT INTO runs(id,location,status,detail) VALUES(?,?,?,?)', ('run-1', '/private/music/FalsePositive.flac', 'completed', ''))
            db.execute('INSERT INTO run_tracks VALUES(?,?)', ('run-1', rows[0][0]))
            db.execute('INSERT INTO stages VALUES(?,?,?)', ('run-1', 'bpm', 'not-json-summary-endpoint-must-not-read-this'))
            db.commit(); db.close()

            repo = ReadOnlyExplorerSQLiteRepository(str(path))

            _metadata, artist_count, artist_page, _cursor = repo.list_track_summaries(10, query='artist', order='title')
            self.assertEqual(artist_count, 1)
            self.assertEqual(tuple(row.handle for row in artist_page), (rows[1][0],))
            _metadata, private_count, private_page, _cursor = repo.list_track_summaries(10, query='private', order='title')
            self.assertEqual(private_count, 0)
            self.assertEqual(private_page, ())
            _metadata, case_count, case_page, _cursor = repo.list_track_summaries(10, query='mixed case', order='title')
            self.assertEqual(case_count, 1)
            self.assertEqual(tuple(row.handle for row in case_page), (rows[2][0],))

if __name__ == '__main__':
    unittest.main()


class _FakeCompactCursor:
    def __init__(self, rows):
        self._rows = tuple(rows)

    def fetchall(self):
        return self._rows

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def __iter__(self):
        return iter(self._rows)


class _FakeCompactDb:
    def __init__(self, expected_size_expression=None):
        self.queries = []
        self.expected_size_expression = expected_size_expression

    def execute(self, sql, params=()):
        compact = ' '.join(sql.split())
        self.queries.append(compact)
        if 'SELECT t.id, t.sha256, t.size' in compact:
            return _FakeCompactCursor(())
        if 'FROM latest_run JOIN stages s' in compact:
            if ', s.result' in compact:
                raise MemoryError('stage payload was fetched before size preflight')
            if self.expected_size_expression is not None:
                expected = f'SELECT s.run_id, s.stage, {self.expected_size_expression} FROM latest_run JOIN stages s'
                if expected not in compact:
                    raise AssertionError('unexpected stage size SQL: ' + compact)
            return _FakeCompactCursor((('run', 'bpm', 17 * 1024 * 1024),))
        if 'FROM overrides o' in compact:
            return _FakeCompactCursor(())
        raise AssertionError('unexpected SQL: ' + compact)


class _FakeReadTrackCursor:
    def __init__(self, rows):
        self._rows = tuple(rows)

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return self._rows

    def __iter__(self):
        return iter(self._rows)


class _FakeOversizedReadTrackDb:
    def __init__(self, expected_size_expression=None):
        self.queries = []
        self.expected_size_expression = expected_size_expression

    def execute(self, sql, params=()):
        compact = ' '.join(sql.split())
        self.queries.append(compact)
        if compact.startswith('SELECT id,sha256,size FROM tracks'):
            return _FakeReadTrackCursor((('sha256:' + '8' * 64, '8' * 64, 1),))
        if compact.startswith('SELECT path FROM locations'):
            return _FakeReadTrackCursor((('/music/Oversized.flac',),))
        if compact.startswith('SELECT r.id,r.status,r.detail FROM runs'):
            return _FakeReadTrackCursor((('run-oversized', 'completed', ''),))
        if self.expected_size_expression is None and (
            compact.startswith('SELECT stage,octet_length(result) FROM stages')
            or compact.startswith('SELECT stage,length(CAST(result AS BLOB)) FROM stages')
        ):
            return _FakeReadTrackCursor((('bpm', 17 * 1024 * 1024), ('energy', 1)))
        if self.expected_size_expression is not None and compact.startswith(f'SELECT stage,{self.expected_size_expression} FROM stages'):
            return _FakeReadTrackCursor((('bpm', 17 * 1024 * 1024), ('energy', 1)))
        if compact.startswith('SELECT result FROM stages'):
            raise MemoryError('stage payload was fetched before size preflight')
        raise AssertionError('unexpected SQL: ' + compact)


class StandaloneReadOnlyExplorerStagePayloadGuardTests(unittest.TestCase):
    def test_read_track_rejects_oversized_stage_before_fetching_any_stage_payload(self):
        repo = ReadOnlyExplorerSQLiteRepository.__new__(ReadOnlyExplorerSQLiteRepository)
        fake_db = _FakeOversizedReadTrackDb()

        with self.assertRaisesRegex(AnalysisError, 'Oversized stored stage'):
            repo._read_track(fake_db, 'sha256:' + '8' * 64)

        self.assertFalse(any(query.startswith('SELECT result FROM stages') for query in fake_db.queries))

    def test_read_track_uses_octet_length_preflight_on_modern_sqlite(self):
        repo = ReadOnlyExplorerSQLiteRepository.__new__(ReadOnlyExplorerSQLiteRepository)
        fake_db = _FakeOversizedReadTrackDb('octet_length(result)')
        original_version = standalone_explorer_readonly_module.sqlite3.sqlite_version_info
        standalone_explorer_readonly_module.sqlite3.sqlite_version_info = (3, 43, 0)
        try:
            with self.assertRaisesRegex(AnalysisError, 'Oversized stored stage'):
                repo._read_track(fake_db, 'sha256:' + '8' * 64)
        finally:
            standalone_explorer_readonly_module.sqlite3.sqlite_version_info = original_version

        size_queries = [query for query in fake_db.queries if query.startswith('SELECT stage,')]
        self.assertEqual(['SELECT stage,octet_length(result) FROM stages WHERE run_id=? ORDER BY stage'], size_queries)
        self.assertFalse(any('CAST(result AS BLOB)' in query for query in size_queries))
        self.assertFalse(any(query.startswith('SELECT result FROM stages') for query in fake_db.queries))

    def test_read_track_falls_back_to_byte_accurate_cast_preflight_on_old_sqlite(self):
        repo = ReadOnlyExplorerSQLiteRepository.__new__(ReadOnlyExplorerSQLiteRepository)
        fake_db = _FakeOversizedReadTrackDb('length(CAST(result AS BLOB))')
        original_version = standalone_explorer_readonly_module.sqlite3.sqlite_version_info
        standalone_explorer_readonly_module.sqlite3.sqlite_version_info = (3, 42, 0)
        try:
            with self.assertRaisesRegex(AnalysisError, 'Oversized stored stage'):
                repo._read_track(fake_db, 'sha256:' + '8' * 64)
        finally:
            standalone_explorer_readonly_module.sqlite3.sqlite_version_info = original_version

        size_queries = [query for query in fake_db.queries if query.startswith('SELECT stage,')]
        self.assertEqual(['SELECT stage,length(CAST(result AS BLOB)) FROM stages WHERE run_id=? ORDER BY stage'], size_queries)

    @unittest.skipIf(sqlite3.sqlite_version_info < (3, 43, 0), 'SQLite octet_length unavailable before 3.43')
    def test_octet_length_preflight_measures_utf8_bytes_not_characters(self):
        self.assertEqual('octet_length(result)', standalone_explorer_readonly_module._stage_result_size_expression())
        with closing(sqlite3.connect(':memory:')) as db:
            size = db.execute(
                f'SELECT {standalone_explorer_readonly_module._stage_result_size_expression()} FROM (SELECT ? AS result)',
                ('é',),
            ).fetchone()[0]
        self.assertEqual(len('é'.encode('utf-8')), size)



class StandaloneCompactGraphResourceTests(unittest.TestCase):
    def test_warm_compact_graph_validates_each_feature_evidence_row_once_per_request(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'analysis.sqlite'
            repository = SQLiteAnalysisRepository(str(path))
            identities = (
                _register_graph_track(repository, 'a', '/music/alpha.flac'),
                _register_graph_track(repository, 'b', '/music/beta.flac'),
            )
            for identity, location in zip(identities, ('/music/alpha.flac', '/music/beta.flac')):
                _complete_graph_feature_run(repository, identity, location)

            with closing(sqlite3.connect(path)) as db:
                expected_identities = tuple(db.execute(
                    'SELECT track_id,run_id FROM graph_feature_evidence WHERE is_current=1 ORDER BY track_id,run_id'
                ))
            original_validator = standalone_explorer_readonly_module.validate_graph_feature_evidence_payload
            calls = []

            def counting_validator(track_id, run_id, fingerprint, payload):
                calls.append((track_id, run_id))
                return original_validator(track_id, run_id, fingerprint, payload)

            with patch.object(standalone_explorer_readonly_module, 'validate_graph_feature_evidence_payload', counting_validator):
                graph = ReadOnlyExplorerSQLiteRepository(str(path)).mood_axis_graph_snapshot()

        self.assertIsNotNone(graph)
        self.assertEqual(
            expected_identities,
            tuple(calls),
            'warm compact graph reads should semantically validate each current compact evidence row exactly once per request',
        )

    def test_compact_graph_rejects_oversized_stage_before_fetching_payload(self):
        repo = ReadOnlyExplorerSQLiteRepository.__new__(ReadOnlyExplorerSQLiteRepository)
        fake_db = _FakeCompactDb()

        with self.assertRaisesRegex(AnalysisError, 'Oversized stored stage'):
            repo._compact_graph_tracks(fake_db)

        self.assertFalse(any(', s.result' in query for query in fake_db.queries))

    def test_compact_graph_uses_octet_length_preflight_on_modern_sqlite(self):
        repo = ReadOnlyExplorerSQLiteRepository.__new__(ReadOnlyExplorerSQLiteRepository)
        fake_db = _FakeCompactDb('octet_length(s.result)')
        original_version = standalone_explorer_readonly_module.sqlite3.sqlite_version_info
        standalone_explorer_readonly_module.sqlite3.sqlite_version_info = (3, 43, 0)
        try:
            with self.assertRaisesRegex(AnalysisError, 'Oversized stored stage'):
                repo._compact_graph_tracks(fake_db)
        finally:
            standalone_explorer_readonly_module.sqlite3.sqlite_version_info = original_version

        size_queries = [query for query in fake_db.queries if 'FROM latest_run JOIN stages s' in query]
        self.assertEqual(1, len(size_queries))
        self.assertIn('octet_length(s.result)', size_queries[0])
        self.assertNotIn('CAST(s.result AS BLOB)', size_queries[0])
        self.assertFalse(any(query.startswith('SELECT result FROM stages') for query in fake_db.queries))

    def test_compact_graph_falls_back_to_byte_accurate_cast_preflight_on_old_sqlite(self):
        repo = ReadOnlyExplorerSQLiteRepository.__new__(ReadOnlyExplorerSQLiteRepository)
        fake_db = _FakeCompactDb('length(CAST(s.result AS BLOB))')
        original_version = standalone_explorer_readonly_module.sqlite3.sqlite_version_info
        standalone_explorer_readonly_module.sqlite3.sqlite_version_info = (3, 42, 0)
        try:
            with self.assertRaisesRegex(AnalysisError, 'Oversized stored stage'):
                repo._compact_graph_tracks(fake_db)
        finally:
            standalone_explorer_readonly_module.sqlite3.sqlite_version_info = original_version

        size_queries = [query for query in fake_db.queries if 'FROM latest_run JOIN stages s' in query]
        self.assertEqual(1, len(size_queries))
        self.assertIn('length(CAST(s.result AS BLOB))', size_queries[0])


def _skip_without_posix_address_space_limit():
    if os.name != 'posix' or not hasattr(resource, 'RLIMIT_AS'):
        raise unittest.SkipTest('POSIX RLIMIT_AS is required for deterministic low-memory standalone compact graph coverage')


def _create_standalone_oversized_stage_database(path: Path) -> None:
    SQLiteAnalysisRepository(str(path))
    with closing(sqlite3.connect(path)) as db, db:
        db.execute('PRAGMA foreign_keys=ON')
        track_id = 'sha256:' + 'c' * 64
        db.execute('INSERT INTO tracks(id,sha256,size) VALUES(?,?,?)', (track_id, 'c' * 64, 1))
        db.execute(
            'INSERT INTO locations(path,track_id,mtime_ns,format,available) VALUES(?,?,?,?,1)',
            ('/music/standalone-oversized.flac', track_id, 1, 'flac'),
        )
        db.execute(
            'INSERT INTO track_metadata(track_id,common_json,tags_json,warnings_json) VALUES(?,?,?,?)',
            (track_id, '[]', '[]', '[]'),
        )
        db.execute(
            'INSERT INTO track_audio(track_id,duration_seconds,duration_source,status,reason) VALUES(?,?,?,?,?)',
            (track_id, 120.0, 'mutagen', 'eligible', ''),
        )
        db.execute("INSERT INTO runs(id,location,status,detail) VALUES(?,?, 'completed', '')", ('run-standalone-oversized', '/music/standalone-oversized.flac'))
        db.execute('INSERT INTO run_tracks(run_id,track_id) VALUES(?,?)', ('run-standalone-oversized', track_id))
        db.execute('INSERT INTO stages(run_id,stage,result) VALUES(?,?,zeroblob(?))', ('run-standalone-oversized', 'energy', _OVERSIZED_STAGE_BYTES))


_STANDALONE_OVERSIZED_COMPACT_SCRIPT = r'''
import resource
import sys
from music_explorer.infrastructure.explorer_readonly import AnalysisError, ReadOnlyExplorerSQLiteRepository

path = sys.argv[1]
limit = int(sys.argv[2])
resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
resource.setrlimit(resource.RLIMIT_AS, (limit, limit))
try:
    ReadOnlyExplorerSQLiteRepository(path).mood_axis_graph_snapshot()
except AnalysisError as error:
    print(str(error))
    raise SystemExit(42)
except MemoryError:
    print('MemoryError', file=sys.stderr)
    raise SystemExit(73)
raise SystemExit('expected AnalysisError')
'''


class StandaloneCompactGraphLowMemoryTests(unittest.TestCase):
    def test_standalone_mood_axis_preflights_oversized_stage_under_low_address_space(self):
        _skip_without_posix_address_space_limit()
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'analysis.sqlite'
            _create_standalone_oversized_stage_database(path)
            result = subprocess.run(
                [sys.executable, '-c', _STANDALONE_OVERSIZED_COMPACT_SCRIPT, str(path), str(_MEMORY_LIMIT_BYTES)],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=_TIMEOUT_SECONDS,
            )

        self.assertEqual(result.returncode, 42, (result.stdout, result.stderr))
        self.assertIn('Oversized stored stage (16 MiB limit)', result.stdout)
        self.assertNotIn('MemoryError', result.stderr)


_STANDALONE_OVERSIZED_DETAIL_SCRIPT = r"""
import resource
import sys
from music_explorer.infrastructure.explorer_readonly import AnalysisError, ReadOnlyExplorerSQLiteRepository

path = sys.argv[1]
track_id = sys.argv[2]
limit = int(sys.argv[3])
resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
resource.setrlimit(resource.RLIMIT_AS, (limit, limit))
try:
    ReadOnlyExplorerSQLiteRepository(path).read_track(track_id)
except AnalysisError as error:
    print(str(error))
    raise SystemExit(42)
except MemoryError:
    print('MemoryError', file=sys.stderr)
    raise SystemExit(73)
raise SystemExit('expected AnalysisError')
"""


class StandaloneDetailReadLowMemoryTests(unittest.TestCase):
    def test_standalone_read_track_preflights_oversized_stage_under_low_address_space(self):
        _skip_without_posix_address_space_limit()
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'analysis.sqlite'
            _create_standalone_oversized_stage_database(path)
            track_id = 'sha256:' + 'c' * 64
            result = subprocess.run(
                [sys.executable, '-c', _STANDALONE_OVERSIZED_DETAIL_SCRIPT, str(path), track_id, str(_MEMORY_LIMIT_BYTES)],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=_TIMEOUT_SECONDS,
            )

        self.assertEqual(result.returncode, 42, (result.stdout, result.stderr))
        self.assertIn('Oversized stored stage (16 MiB limit)', result.stdout)
        self.assertNotIn('MemoryError', result.stderr)
