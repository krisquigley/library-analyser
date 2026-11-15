"""PR #107 review follow-ups for scoped ordinary Explorer reads (both mirrors)."""
import itertools
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from music_analyzer.application.dto.analysis import AnalysisError as AnalyzerAnalysisError
from music_analyzer.infrastructure.persistence import explorer_readonly as analyzer_reader
from music_explorer.infrastructure import explorer_readonly as standalone_reader
from tests.acceptance.test_explorer_server import create_db

MIRRORS = (
    ('analyzer', analyzer_reader.ReadOnlyExplorerSQLiteRepository, AnalyzerAnalysisError),
    ('standalone', standalone_reader.ReadOnlyExplorerSQLiteRepository, standalone_reader.AnalysisError),
)


class ScopedReadFollowupTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.path = Path(temp.name) / 'analysis.sqlite'
        self.first, self.second = create_db(self.path)

    def count_candidate_checks(self, repository_class, read):
        original = repository_class._active_candidate
        calls = []

        def counted(repository, *args):
            calls.append(args[0])
            return original(repository, *args)

        with patch.object(repository_class, '_active_candidate', counted):
            read(repository_class(str(self.path)))
        return calls

    def test_list_reads_check_each_catalogue_candidate_once(self):
        reads = {
            'list_tracks': lambda repo: repo.list_tracks(1),
            'list_track_summaries': lambda repo: repo.list_track_summaries(1),
            'search_summaries': lambda repo: repo.list_track_summaries(1, query='flac'),
            'artist_summaries': lambda repo: repo.list_track_summaries(1, order='artist'),
        }
        for (name, repository_class, _error), (read_name, read) in itertools.product(MIRRORS, reads.items()):
            with self.subTest(mirror=name, read=read_name):
                calls = self.count_candidate_checks(repository_class, read)
                self.assertEqual(sorted(calls), [self.first, self.second])

    def test_list_reads_keep_count_page_and_cursor_contract(self):
        for name, repository_class, _error in MIRRORS:
            with self.subTest(mirror=name):
                repo = repository_class(str(self.path))
                _meta, count, tracks = repo.list_tracks(1)
                self.assertEqual((count, [t.track_id for t in tracks]), (2, [self.first]))
                _meta, count, tracks = repo.list_tracks(1, after=self.first)
                self.assertEqual((count, [t.track_id for t in tracks]), (1, [self.second]))
                _meta, count, tracks = repo.list_tracks(1, after=self.second)
                self.assertEqual((count, tracks), (0, ()))

                _meta, count, page, cursor = repo.list_track_summaries(1, order='id')
                self.assertEqual((count, [s.handle for s in page]), (2, [self.first]))
                _meta, count, page, after = repo.list_track_summaries(1, cursor=cursor, order='id')
                # Summary count is the whole match count, independent of the cursor.
                self.assertEqual((count, [s.handle for s in page], after), (2, [self.second], None))
                _meta, count, page, after = repo.list_track_summaries(5, query='no-such-track')
                self.assertEqual((count, page, after), (0, (), None))

    def test_summary_count_is_kept_when_cursor_page_is_empty(self):
        for name, repository_class, _error in MIRRORS:
            with self.subTest(mirror=name):
                repo = repository_class(str(self.path))
                _meta, _count, _page, cursor = repo.list_track_summaries(1, order='id')
                _meta, _count, _page, cursor = repo.list_track_summaries(1, cursor=cursor, order='id')
                self.assertIsNone(cursor)
                last_cursor = repo._encode_summary_cursor(repo._summary_fold(self.second), self.second)
                _meta, count, page, after = repo.list_track_summaries(1, cursor=last_cursor, order='id')
                self.assertEqual((count, page, after), (2, (), None))

    def test_any_orphan_run_link_for_selected_track_aborts_detail(self):
        db = sqlite3.connect(self.path)
        db.execute('PRAGMA foreign_keys=OFF')
        # A valid run remains linked; the extra link points at a missing run.
        db.execute('INSERT INTO run_tracks(run_id, track_id) VALUES(?,?)', ('missing-run', self.first))
        db.commit()
        db.close()
        for name, repository_class, error in MIRRORS:
            with self.subTest(mirror=name):
                with self.assertRaises(error) as raised:
                    repository_class(str(self.path)).read_track(self.first)
                self.assertEqual(str(raised.exception), 'Unexpected analysis database rows')
                # Unrelated tracks stay readable.
                self.assertEqual(repository_class(str(self.path)).read_track(self.second).track_id, self.second)


class MirrorAudioValidationParityTests(unittest.TestCase):
    """Both mirrors must accept/reject the same stored audio rows."""

    def test_audio_validation_agrees_across_mirrors(self):
        durations = (None, 0, -1.0, 0.5, 120, 120.0, 1200.0, 1200.01, float('inf'), float('nan'), True, '120')
        sources = ('', 'mutagen', 'ffprobe', 'tags', None)
        statuses = ('eligible', 'excluded', 'unknown')
        reasons = {''}
        for duration, source in itertools.product(durations, sources):
            try:
                reasons.add(standalone_reader._duration_warning(duration, source))
            except TypeError:
                pass
        analyzer = analyzer_reader.ReadOnlyExplorerSQLiteRepository.__new__(analyzer_reader.ReadOnlyExplorerSQLiteRepository)
        standalone = standalone_reader.ReadOnlyExplorerSQLiteRepository.__new__(standalone_reader.ReadOnlyExplorerSQLiteRepository)

        def outcome(repository, args):
            try:
                repository._validate_audio(*args)
                return 'accepted'
            except (AnalyzerAnalysisError, standalone_reader.AnalysisError):
                return 'rejected'

        for args in itertools.product(durations, sources, statuses, sorted(reasons)):
            with self.subTest(args=args):
                self.assertEqual(outcome(analyzer, args), outcome(standalone, args))


if __name__ == '__main__':
    unittest.main()
