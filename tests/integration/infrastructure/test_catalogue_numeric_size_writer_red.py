"""Register must preserve the reader's persisted integer-size contract.

SQLite retains 0.5 as REAL in tracks.size; the public read-only repository's
row validation requires a nonnegative int. FileIdentity currently admits 0.5,
so exercise the public catalogue writer, not a synthetic corrupt database.
Behavior is exercised and observed through public APIs. An independent
read-only snapshot of the synthetic fixture also covers scan roots, raw audio
status/reason, and current/noncurrent warm graph history; it never accesses
the writer's private connection or mutates persisted data.
"""
from contextlib import closing
from dataclasses import replace
from pathlib import Path
import sqlite3
import tempfile
import unittest

from music_analyzer.application.dto.analysis import AnalysisError
from music_analyzer.application.dto.catalogue import Inventory, ScannedFile, TrackMetadata
from music_analyzer.domain.catalogue import FileIdentity
from music_analyzer.domain.projection import ProjectionEdge
from music_analyzer.infrastructure.persistence.analysis import SQLiteAnalysisRepository
from music_analyzer.infrastructure.persistence.explorer_readonly import ReadOnlyExplorerSQLiteRepository


class CatalogueNumericSizeWriterTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name) / 'music'
        self.root.mkdir()
        self.path = Path(directory.name) / 'analysis.sqlite'
        self.writer = SQLiteAnalysisRepository(str(self.path))
        self.original = tuple(
            ScannedFile(
                str(self.root / f'{suffix}.flac'), FileIdentity(suffix * 64, 123), 1, 'flac',
                TrackMetadata(common=(('title', f'Original {suffix}'),),
                              tags=(('TITLE', (f'Original {suffix}',)),),
                              warnings=('retained warning',),
                              duration_seconds=180.0, duration_source='mutagen'),
            )
            for suffix in ('a', 'b')
        )
        self.assertEqual(self.writer.register(self._inventory(self.original)), ())
        self.revision = self.writer.source_revision()
        historical_edges = (ProjectionEdge(self.original[0].identity.track_id,
                                           self.original[1].identity.track_id, 0.5, 1),)
        self.historical_build_id = self.writer.replace_graph_snapshot(
            historical_edges, 2, 'integer-size-history', positioned_edges=historical_edges,
            source_revision=self.revision,
        )
        edges = (ProjectionEdge(self.original[0].identity.track_id,
                                self.original[1].identity.track_id, 0.25, 2),)
        self.build_id = self.writer.replace_graph_snapshot(
            edges, 2, 'integer-size-baseline', positioned_edges=edges,
            source_revision=self.revision,
        )
        self.assertEqual(tuple(self.writer.track_ids()),
                         tuple(item.identity.track_id for item in self.original))
        self.assertEqual(self.writer.current_graph_snapshot(2, self.revision)['state'], 'ready')

    def _inventory(self, files):
        return Inventory(str(self.root), tuple(files), (), True)

    def _replacement(self, size):
        # The first item proposes real mutations before the late bad identity:
        # metadata, location and mtime change. The complete scan also
        # proposes making both old paths unavailable. The second identity is
        # fresh, so existing-row equality cannot accidentally supply rejection.
        first = replace(
            self.original[0], location=str(self.root / 'moved.flac'), mtime_ns=2,
            metadata=TrackMetadata(common=(('title', 'Changed first'),),
                                   tags=(('TITLE', ('Changed first',)),),
                                   duration_seconds=180.0, duration_source='mutagen'),
        )
        second = ScannedFile(
            str(self.root / 'fresh.flac'), FileIdentity('c' * 64, size), 3, 'flac',
            TrackMetadata(common=(('title', 'Fresh second'),),
                          duration_seconds=200.0, duration_source='mutagen'),
        )
        return (first, second)

    def _persisted_snapshot(self):
        # Independent observation of this synthetic fixture, not a private
        # writer connection. Include every persisted value and retained build.
        with closing(sqlite3.connect(self.path.as_uri() + '?mode=ro', uri=True)) as db:
            db.execute('PRAGMA query_only=ON')
            return '\n'.join(db.iterdump()).encode('utf-8')

    def _public_state(self):
        reader = ReadOnlyExplorerSQLiteRepository(str(self.path))
        ids = tuple(self.writer.track_ids())
        return {
            'writer_ids': ids,
            'writer_tracks': tuple(self.writer.read_track(track_id) for track_id in ids),
            'writer_locations': tuple((track_id, self.writer.locations(track_id)) for track_id in ids),
            'source_revision': self.writer.source_revision(),
            'warm_status': self.writer.current_graph_snapshot(2, self.revision),
            'reader_metadata': reader.metadata(),
            'reader_ids': reader.track_ids(),
            'reader_tracks': tuple(reader.read_track(track_id) for track_id in ids),
            'reader_list': reader.list_tracks(10),
            'reader_summaries': reader.list_track_summaries(10),
            'reader_paths': reader.available_audio_paths(),
            'reader_candidates': reader.candidate_snapshot(),
            'reader_graph_sources': tuple(reader.graph_source_tracks()),
            'warm_edges': reader.current_graph_edges(2),
            'warm_positioned_edges': reader.current_positioned_graph_edges(2),
        }

    def _assert_corrected_retry_succeeds(self):
        corrected = self._replacement(456)
        missing = self.writer.register(self._inventory(corrected))
        self.assertEqual(missing, tuple(sorted(item.location for item in self.original)))
        self.assertEqual(tuple(self.writer.track_ids()),
                         (self.original[0].identity.track_id, self.original[1].identity.track_id,
                          corrected[1].identity.track_id))
        self.assertEqual(self.writer.locations(self.original[1].identity.track_id), ())
        self.assertNotEqual(self.writer.current_graph_snapshot(2, self.revision)['state'], 'ready')
        reader = ReadOnlyExplorerSQLiteRepository(str(self.path))
        self.assertEqual(reader.track_ids(), tuple(self.writer.track_ids()))
        self.assertEqual(reader.available_audio_paths(), tuple(sorted(item.location for item in corrected)))
        for item in corrected:
            stored = reader.read_track(item.identity.track_id)
            self.assertEqual(stored.size, item.identity.size)
            self.assertEqual(stored.metadata, item.metadata)
            self.assertEqual(self.writer.locations(item.identity.track_id), (item.location,))
        reopened = SQLiteAnalysisRepository(str(self.path))
        self.assertEqual(reopened.read_track(corrected[1].identity.track_id).size, 456)

    def test_register_rejects_late_fresh_fractional_size_without_public_state_change_and_allows_retry(self):
        before = self._public_state()
        persisted_before = self._persisted_snapshot()
        malformed = self._replacement(0.5)
        fresh_id = malformed[1].identity.track_id
        self.assertNotIn(fresh_id, before['writer_ids'])
        # Repeat the rejected call to prove no leaked fresh row, missing-path
        # marking or graph invalidation poisons a retry of the same inventory.
        for _ in range(2):
            with self.assertRaises(AnalysisError,
                                   msg='register must reject a fresh persisted REAL size=0.5') as rejected:
                self.writer.register(self._inventory(malformed))
            self.assertRegex(str(rejected.exception), r'(?i)identity|size')
            self.assertRegex(str(rejected.exception), r'(?i)invalid|numeric|integer|persisted|nonnegative')
            self.assertEqual(self._persisted_snapshot(), persisted_before,
                             'rejection must retain roots/audio/current and historical graph state')
            self.assertEqual(self._public_state(), before)
            self.assertNotIn(fresh_id, tuple(self.writer.track_ids()))
            self.assertEqual(self.writer.locations(fresh_id), ())
            with self.assertRaises(AnalysisError):
                self.writer.read_track(fresh_id)
            self.assertEqual(self.writer.current_graph_snapshot(2, self.revision)['build_id'],
                             self.build_id)
        self._assert_corrected_retry_succeeds()

    def test_valid_integer_size_replacement_is_accepted_and_public_reader_remains_usable(self):
        self._public_state()
        self._assert_corrected_retry_succeeds()

    def test_two_integer_size_entries_have_readable_ready_warm_baseline(self):
        state = self._public_state()
        self.assertEqual(state['reader_ids'], state['writer_ids'])
        self.assertEqual(state['reader_paths'], tuple(item.location for item in self.original))
        self.assertEqual(state['warm_status']['build_id'], self.build_id)
        self.assertNotEqual(self.historical_build_id, self.build_id)
        snapshot = self._persisted_snapshot()
        self.assertIn(self.historical_build_id.encode('utf-8'), snapshot)
        self.assertIn(self.build_id.encode('utf-8'), snapshot)
        self.assertTrue(state['warm_edges'])
        self.assertTrue(state['warm_positioned_edges'])
        for item, stored in zip(self.original, state['reader_tracks']):
            self.assertEqual(stored.size, 123)
            self.assertEqual(stored.metadata, item.metadata)


if __name__ == '__main__':
    unittest.main()
