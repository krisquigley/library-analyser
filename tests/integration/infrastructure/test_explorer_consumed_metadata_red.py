"""Issue88 P6: metadata consumed by query/order is not a fallback signal.

Public four-track writer-schema fixture; only a scoped external SQL update
corrupts metadata. FULL reader validation is deliberately not patched/removed.
"""
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from music_analyzer.application.dto.analysis import AnalysisError as AnalyzerError
from music_analyzer.application.dto.catalogue import Inventory, ScannedFile, TrackMetadata
from music_analyzer.domain.catalogue import FileIdentity
from music_analyzer.infrastructure.persistence.analysis import SQLiteAnalysisRepository
from music_analyzer.infrastructure.persistence.explorer_readonly import ReadOnlyExplorerSQLiteRepository as AnalyzerReader
from music_explorer.infrastructure.explorer_readonly import AnalysisError as ExplorerError
from music_explorer.infrastructure.explorer_readonly import ReadOnlyExplorerSQLiteRepository as ExplorerReader


PRIVATE_MARKER = 'fixture-private-value-not-for-errors'


def create_public_fixture(path):
    root = path.parent / PRIVATE_MARKER
    files = tuple(
        ScannedFile(str(root / f'{number}.flac'), FileIdentity(f'{number:064x}', 10), 1, 'flac',
                    TrackMetadata(common=(('title', title), ('artist', artist)),
                                  tags=(('comment', (PRIVATE_MARKER,)),),
                                  warnings=(PRIVATE_MARKER,), duration_seconds=120.0,
                                  duration_source='mutagen'))
        for number, title, artist in (
            (1, 'Alpha Beacon', 'Ada'), (2, 'Beta Beacon', 'Ben'),
            (3, 'Gamma Beacon', 'Cora'), (4, 'Zulu Beacon', 'Zed'))
    )
    SQLiteAnalysisRepository(str(path)).register(Inventory(str(root), files, (), True))
    return tuple(file.identity.track_id for file in files)


def stored_snapshot(path):
    with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)) as db:
        db.execute('PRAGMA query_only=ON')
        return tuple(db.iterdump())


def corrupt_common(path, handle, payload='{"title":"Bad"}'):
    # Do not feed malformed metadata to the writer: PR92 already rejects that.
    with closing(sqlite3.connect(path)) as db:
        db.execute('UPDATE track_metadata SET common_json=? WHERE track_id=?', (payload, handle))
        db.commit()


class ExplorerConsumedMetadataTests(unittest.TestCase):
    readers = ((AnalyzerReader, AnalyzerError), (ExplorerReader, ExplorerError))

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / 'public.sqlite'
        self.handles = create_public_fixture(self.path)

    def assert_clear_error(self, repo, error_type, **request):
        before = stored_snapshot(self.path)
        with self.assertRaises(error_type) as raised:
            repo.list_track_summaries(1, **request)
        # Stable category, not SQLite's opaque "user-defined function raised
        # exception", mapper internals, raw JSON, track identity, or file paths.
        self.assertEqual(str(raised.exception), 'Invalid stored metadata')
        self.assertNotIn(PRIVATE_MARKER, str(raised.exception))
        self.assertEqual(stored_snapshot(self.path), before)

    def test_sort_consumed_unreturned_object_metadata_must_fail_clearly(self):
        for reader, error_type in self.readers:
            for order in ('title', 'artist'):
                with self.subTest(reader=reader.__module__, order=order):
                    # On the healthy fixture the fourth row is neither returned
                    # nor LIMIT+1 lookahead. Sorting nevertheless evaluates it.
                    healthy = reader(str(self.path)).list_track_summaries(1, order=order)
                    self.assertEqual(healthy[1], 4)
                    self.assertEqual(tuple(row.handle for row in healthy[2]), self.handles[:1])
                    self.assertTrue(healthy[3])
                    corrupt_common(self.path, self.handles[3])
                    self.assert_clear_error(reader(str(self.path)), error_type, order=order)
                # Restore externally for the next independent subtest.
                corrupt_common(self.path, self.handles[3], json.dumps([['title', 'Zulu Beacon'], ['artist', 'Zed']]))

    def test_query_consumed_nonmatching_object_metadata_must_fail_clearly(self):
        corrupt_common(self.path, self.handles[3])
        for reader, error_type in self.readers:
            with self.subTest(reader=reader.__module__):
                # Bad's fabricated ID/empty artist cannot match beacon; the
                # current bug returns a misleading count=3/page instead.
                self.assert_clear_error(reader(str(self.path)), error_type, query='beacon', order='id')

    def test_late_evaluated_common_and_tags_errors_are_sanitized(self):
        for column in ('common_json', 'tags_json'):
            for payload in ('{}', 'null', '""', '{', '[null]', '[["title"]]'):
                for reader, error_type in self.readers:
                    with self.subTest(column=column, payload=payload, reader=reader.__module__):
                        with closing(sqlite3.connect(self.path)) as db:
                            original = db.execute(f'SELECT {column} FROM track_metadata WHERE track_id=?', (self.handles[3],)).fetchone()[0]
                            db.execute(f'UPDATE track_metadata SET {column}=? WHERE track_id=?', (payload, self.handles[3]))
                            db.commit()
                        try:
                            self.assert_clear_error(reader(str(self.path)), error_type, order='artist')
                            self.assert_clear_error(reader(str(self.path)), error_type, query='beacon', order='id')
                        finally:
                            with closing(sqlite3.connect(self.path)) as db:
                                db.execute(f'UPDATE track_metadata SET {column}=? WHERE track_id=?', (original, self.handles[3]))
                                db.commit()

    def test_selected_id_page_metadata_error_is_sanitized(self):
        corrupt_common(self.path, self.handles[0])
        for reader, error_type in self.readers:
            with self.subTest(reader=reader.__module__):
                self.assert_clear_error(reader(str(self.path)), error_type, order='id')

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
                    for reader, error_type in self.readers:
                        with self.subTest(column=column, index=index, reader=reader.__module__, payload=payload[:60]):
                            repo = reader(str(self.path))
                            self.assert_clear_error(repo, error_type, order='id' if index == 0 else 'title')
                            if index == 3:
                                self.assert_clear_error(repo, error_type, query='beacon', order='id')
                finally:
                    with closing(sqlite3.connect(self.path)) as db:
                        db.execute(f'UPDATE track_metadata SET {column}=? WHERE track_id=?', (original, self.handles[index]))
                        db.commit()

    def test_failure_context_is_not_shared_between_requests(self):
        corrupt_common(self.path, self.handles[3])
        for reader, error_type in self.readers:
            repo = reader(str(self.path))
            with self.subTest(reader=reader.__module__):
                with ThreadPoolExecutor(max_workers=2) as pool:
                    failed = pool.submit(repo.list_track_summaries, 1, order='title')
                    healthy = pool.submit(repo.list_track_summaries, 1, order='id')
                    with self.assertRaises(error_type) as raised:
                        failed.result(timeout=5)
                    self.assertEqual(str(raised.exception), 'Invalid stored metadata')
                    self.assertEqual(healthy.result(timeout=5)[1], 4)
                self.assertEqual(repo.list_track_summaries(1, order='id')[1], 4)

    def test_valid_scalar_and_text_lists_and_empty_optional_metadata(self):
        for common, tags in (([['title', 'Alpha Beacon']], []),
                             ([['title', ['Alpha Beacon']], ['artist', []]], [['comment', []]]),
                             ([], [])):
            with closing(sqlite3.connect(self.path)) as db:
                db.execute('UPDATE track_metadata SET common_json=?,tags_json=? WHERE track_id=?',
                           (json.dumps(common), json.dumps(tags), self.handles[0]))
                db.commit()
            for reader, _error_type in self.readers:
                with self.subTest(reader=reader.__module__, common=common):
                    page = reader(str(self.path)).list_track_summaries(1, order='id')
                    self.assertEqual(page[1], 4)
                    self.assertEqual(page[2][0].handle, self.handles[0])

    def test_nested_decoder_failure_context_is_request_local(self):
        corrupt_common(self.path, self.handles[3], '[' * 10000 + '0' + ']' * 10000)
        for reader, error_type in self.readers:
            repo = reader(str(self.path))
            with ThreadPoolExecutor(max_workers=2) as pool:
                failed = pool.submit(repo.list_track_summaries, 1, order='title')
                healthy = pool.submit(repo.list_track_summaries, 1, order='id')
                with self.assertRaises(error_type) as raised:
                    failed.result(timeout=5)
                self.assertEqual(str(raised.exception), 'Invalid stored metadata')
                self.assertEqual(healthy.result(timeout=5)[1], 4)
            self.assertEqual(repo.list_track_summaries(1, order='id')[1], 4)

    def test_valid_pages_counts_cursors_and_query_contracts_are_unchanged(self):
        before = stored_snapshot(self.path)
        for reader, _error_type in self.readers:
            repo = reader(str(self.path))
            for order in ('title', 'artist', 'id'):
                cursor, handles, metadata = None, [], None
                for number in range(4):
                    page_metadata, count, rows, cursor = repo.list_track_summaries(1, cursor=cursor, order=order)
                    self.assertEqual(count, 4)
                    if metadata is not None:
                        self.assertEqual(page_metadata, metadata)
                    metadata = page_metadata
                    handles.extend(row.handle for row in rows)
                    self.assertEqual(bool(cursor), number < 3)
                self.assertEqual(tuple(handles), self.handles)
            self.assertEqual(repo.list_track_summaries(1, query='ALPHA BEACON')[1], 1)
            # Analyzer retains phrase search; standalone retains token-AND.
            self.assertEqual(repo.list_track_summaries(1, query='beacon alpha')[1],
                             0 if reader is AnalyzerReader else 1)
            for literal in ('%', '_', '\\'):
                self.assertEqual(repo.list_track_summaries(1, query=literal)[1], 0)
        self.assertEqual(stored_snapshot(self.path), before)

    def test_unrelated_metadata_does_not_block_id_page_or_detail(self):
        corrupt_common(self.path, self.handles[3])
        before = stored_snapshot(self.path)
        for reader, _error_type in self.readers:
            repo = reader(str(self.path))
            metadata, count, rows, cursor = repo.list_track_summaries(1, order='id')
            self.assertEqual(count, 4)
            self.assertEqual(tuple(row.handle for row in rows), self.handles[:1])
            self.assertTrue(cursor)
            self.assertEqual(repo.read_track(self.handles[0]).track_id, self.handles[0])
        self.assertEqual(stored_snapshot(self.path), before)


if __name__ == '__main__':
    unittest.main()
