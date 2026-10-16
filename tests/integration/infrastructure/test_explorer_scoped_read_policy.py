"""Issue88 R1 ordinary-read policy; public writer-v10 fixture, no reader bypass.

External SQL corruption is explicitly NOT a supported-writer defect. Count and
ordered pagination remain real SQL work; only validation-only work is forbidden.
"""
from contextlib import closing, contextmanager
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from music_analyzer.application.dto.analysis import AudioSource, StageResult
from music_analyzer.application.dto.catalogue import Inventory, ScannedFile, TrackMetadata
from music_analyzer.domain.catalogue import FileIdentity
from music_analyzer.infrastructure.persistence.analysis import SQLiteAnalysisRepository
from music_analyzer.infrastructure.persistence import explorer_readonly as analyzer
from music_explorer.infrastructure import explorer_readonly as standalone
from music_analyzer.infrastructure.persistence.integrity import SQLiteIntegrityScanner

MIRRORS = (analyzer, standalone)


def create_fixture(path):
    writer = SQLiteAnalysisRepository(str(path))
    files = tuple(ScannedFile(
        f'/public/issue88/{i}.flac', FileIdentity(f'{i:064x}', 10), 1, 'flac',
        TrackMetadata(common=(('title', f'Beacon {i:03}'),),
                      duration_seconds=120.0, duration_source='mutagen'))
        for i in range(1, 102))
    excluded = ScannedFile('/public/issue88/excluded.flac', FileIdentity(f'{102:064x}', 10), 1, 'flac',
                           TrackMetadata(duration_seconds=0.0, duration_source='mutagen'))
    # Existing helper writes all five graph-relevant stages through public APIs.
    from tests.integration.infrastructure.test_compact_mood_axis_graph_red import add_positioned_track_identity
    for _ in range(2):
        add_positioned_track_identity(writer, files[0].identity, files[0].location)
    writer.register(Inventory('/public/issue88', (*files, excluded), (), True))
    with closing(sqlite3.connect(path)) as db:
        runs = tuple(row[0] for row in db.execute('SELECT id FROM runs ORDER BY rowid'))
        assert db.execute('SELECT count(*) FROM graph_feature_evidence WHERE is_current=0').fetchone() == (1,)
    return tuple(f.identity.track_id for f in files), runs


@contextmanager
def observe_sql(repo):
    statements = []
    original = repo._connection
    @contextmanager
    def observed():
        with original() as db:
            db.set_trace_callback(statements.append)
            yield db
    with patch.object(repo, '_connection', observed):
        yield statements


def corrupt_history(path, run):
    with closing(sqlite3.connect(path)) as db, db:
        db.execute('UPDATE graph_feature_evidence SET evidence_json=? WHERE run_id=? AND is_current=0', ('{', run))


class ScopedFixture(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / 'public.sqlite'
        self.handles, self.runs = create_fixture(self.path)
        self.assertLess(self.path.stat().st_size, 512 * 1024 * 1024)

    def pages(self, repo):
        first = repo.list_track_summaries(100, query='beacon', order='title')
        self.assertEqual(first[0]['schema_version'], 10)
        self.assertEqual(first[1], 101)
        self.assertEqual(tuple(row.handle for row in first[2]), self.handles[:100])
        self.assertTrue(first[3])
        second = repo.list_track_summaries(100, cursor=first[3], query='beacon', order='title')
        self.assertEqual(second[1], 101)
        self.assertEqual(tuple(row.handle for row in second[2]), self.handles[100:])
        self.assertIsNone(second[3])
        return first, second


class ScopedReadPositiveControls(ScopedFixture):
    def test_real_writer_101_count_first100_next_and_detail(self):
        for module in MIRRORS:
            with self.subTest(mirror=module.__name__):
                repo = module.ReadOnlyExplorerSQLiteRepository(str(self.path))
                self.pages(repo)
                self.assertIsNotNone(repo.read_track(self.handles[1]))

    def test_explicit_diagnostic_detects_unrelated_historical_corruption(self):
        self.assertFalse(SQLiteIntegrityScanner().scan(str(self.path)).findings)
        corrupt_history(self.path, self.runs[0])
        findings = SQLiteIntegrityScanner().scan(str(self.path)).findings
        self.assertTrue(any(f.check_id == 'historical_evidence' and f.code == 'evidence_json_invalid'
                            for f in findings), findings)


class ScopedReadPolicyRedTests(ScopedFixture):
    def test_ordinary_pages_and_detail_do_no_validation_only_schema_graph_history_work(self):
        for module in MIRRORS:
            repo = module.ReadOnlyExplorerSQLiteRepository(str(self.path))
            for operation in ('metadata', 'pages', 'detail'):
                with self.subTest(mirror=module.__name__, operation=operation):
                    with observe_sql(repo) as statements:
                        if operation == 'metadata':
                            self.assertEqual(repo.metadata()['schema_version'], 10)
                        elif operation == 'pages':
                            self.pages(repo)
                        else:
                            self.assertIsNotNone(repo.read_track(self.handles[1]))
                    sql = [' '.join(s.lower().split()) for s in statements]
                    if operation == 'pages':
                        self.assertTrue(any('count(' in s for s in sql), sql)
                        self.assertTrue(any('limit 101' in s for s in sql), sql)
                    forbidden = [s for s in sql if any(token in s for token in (
                        'sqlite_master', 'table_info(', 'index_list(', 'foreign_key_list(',
                        'foreign_key_check', 'graph_build', 'graph_edges',
                        'graph_positioned_edges', 'graph_feature_evidence'))]
                    self.assertEqual(forbidden, [], 'Ordinary request executed validation-only schema/graph/history work')

    def test_unrelated_historical_evidence_does_not_block_search_pages_or_detail(self):
        for module in MIRRORS:
            repo = module.ReadOnlyExplorerSQLiteRepository(str(self.path))
            self.pages(repo)
            self.assertIsNotNone(repo.read_track(self.handles[1]))
        corrupt_history(self.path, self.runs[0])
        for module in MIRRORS:
            repo = module.ReadOnlyExplorerSQLiteRepository(str(self.path))
            for operation in ('pages', 'detail'):
                with self.subTest(mirror=module.__name__, operation=operation):
                    try:
                        if operation == 'pages':
                            self.pages(repo)
                        else:
                            self.assertIsNotNone(repo.read_track(self.handles[1]))
                    except module.AnalysisError as error:
                        self.fail(f'Unrelated historical evidence blocked ordinary {operation}: {error}')
