"""Issue #88 revised P4: direct writer must enforce the existing review policy.

No ReviewTracks use case is involved: this is the SQLite implementation of the
review port. The public two-track fixture retains full and positioned current
and historical graphs. Reader FULL/UI100 policy is deliberately untouched.
"""
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from music_analyzer.application.dto.analysis import AnalysisError, AudioSource, StageResult
from music_analyzer.application.dto.catalogue import Inventory, ScannedFile, TrackMetadata
from music_analyzer.domain.catalogue import FileIdentity
from music_analyzer.domain.projection import ProjectionEdge
from music_analyzer.domain.review import validate_override
from music_analyzer.infrastructure.persistence.analysis import SQLiteAnalysisRepository


class DirectOverrideWriterOriginTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / 'analysis.sqlite'
        self.writer = SQLiteAnalysisRepository(str(self.path))
        files = tuple(
            ScannedFile(
                f'/synthetic/{suffix}.flac', FileIdentity(suffix * 64, 123), 1, 'flac',
                TrackMetadata(duration_seconds=180.0, duration_source='mutagen'),
            )
            for suffix in ('a', 'b')
        )
        self.writer.register(Inventory('/synthetic', files, (), True))
        self.track, other = (item.identity.track_id for item in files)
        for item in files:
            run = self.writer.start(AudioSource(item.location, item.identity.track_id))
            self.writer.save_stage(run, StageResult('bpm', (), 'synthetic estimate', (('bpm', 120.0),)))
            self.writer.finish(run, 'completed', '')
        # Existing value proves rejection cannot erase a prior annotation.
        self.writer.set_override(self.track, 'bpm', '121')
        self.edges = (ProjectionEdge(self.track, other, 0.25, 2),)
        self.revision = self.writer.source_revision()
        self.historical_id = self._publish('historical')
        self.current_id = self._publish('current')
        self.peer = SQLiteAnalysisRepository(str(self.path))
        self._assert_ready()
        self.history = self._retained_graph_rows()
        self.assertEqual(len(self.history[1]), 2)
        self.assertEqual(len(self.history[2]), 2)

    def _publish(self, fingerprint):
        return self.writer.replace_graph_snapshot(
            self.edges, 1, fingerprint, positioned_edges=self.edges,
            source_revision=self.writer.source_revision(),
        )

    def _dump(self):
        # All logical persisted values, including evidence, runs, overrides,
        # revisions, publication pointers, timestamps and both mirror families.
        with closing(sqlite3.connect(self.path)) as db:
            return '\n'.join(db.iterdump()).encode('utf-8')

    def _retained_graph_rows(self):
        with closing(sqlite3.connect(self.path)) as db:
            return tuple(
                tuple(db.execute(f'SELECT * FROM {table} ORDER BY 1,2'))
                for table in ('graph_build_positioned_snapshots', 'graph_build_edges',
                              'graph_build_positioned_edges')
            )

    def _assert_ready(self):
        self.assertEqual(self.peer.source_revision(), self.revision)
        status = self.peer.current_graph_snapshot(1, self.revision)
        self.assertEqual(status['state'], 'ready')
        self.assertEqual(status['build_id'], self.current_id)
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM graph_edges').fetchone()[0], 1)
            self.assertEqual(db.execute('SELECT count(*) FROM graph_positioned_edges').fetchone()[0], 1)
            self.assertEqual(
                db.execute('SELECT id,is_current FROM graph_builds ORDER BY id').fetchall(),
                sorted(((self.historical_id, 0), (self.current_id, 1))),
            )

    def _assert_invalid_then_retry(self, field, value, message):
        # Sanity check: this is an established pure rule, not an invented policy.
        with self.assertRaisesRegex(ValueError, message):
            validate_override(field, value)
        before = self._dump()
        # The task explicitly requires rejection before transaction/invalidation.
        # This narrow transaction-entry spy observes that boundary; it wraps the
        # real operation and does not stub validation, SQL or invalidation.
        with patch.object(self.writer, '_transaction',
                          wraps=self.writer._transaction) as transaction:
            with self.assertRaisesRegex(AnalysisError, message):
                self.writer.set_override(self.track, field, value)
            transaction.assert_not_called()
        self.assertEqual(self._dump(), before)
        self._assert_ready()
        self.assertEqual(dict(self.peer.read_track(self.track).overrides)['bpm'], '121')
        self.assertEqual(self._retained_graph_rows(), self.history)
        self.writer.set_override(self.track, 'bpm', '122')
        self.assertEqual(dict(self.peer.read_track(self.track).overrides)['bpm'], '122')
        self._assert_graph_invalidated()
        retry = self._publish('valid-override-retry')
        self.assertEqual(self.peer.current_graph_snapshot(1, self.peer.source_revision())['build_id'], retry)

    def _assert_graph_invalidated(self):
        self.assertNotEqual(self.peer.source_revision(), self.revision)
        self.assertNotEqual(self.peer.current_graph_snapshot(1, self.peer.source_revision())['state'], 'ready')
        self.assertEqual(self._retained_graph_rows(), self.history)
        with closing(sqlite3.connect(self.path)) as db:
            for table in ('graph_edges', 'graph_positioned_edges'):
                self.assertEqual(db.execute(f'SELECT count(*) FROM {table}').fetchone()[0], 0)
            self.assertEqual(db.execute('SELECT count(*) FROM graph_builds WHERE is_current=1').fetchone()[0], 0)
            self.assertEqual(db.execute('SELECT count(*) FROM graph_builds').fetchone()[0], 2)

    def test_direct_blank_bpm_rejected_before_transaction_with_unchanged_state_and_retry(self):
        self._assert_invalid_then_retry('bpm', '', 'Override must be nonblank text of at most 4096 characters')

    def test_direct_unsupported_field_rejected_before_transaction_with_unchanged_state_and_retry(self):
        self._assert_invalid_then_retry('unsupported', 'annotation', 'Override field must be one of:')

    def test_direct_unsupported_reset_rejected_before_transaction_with_unchanged_state_and_retry(self):
        self._assert_invalid_then_retry('unsupported', None, 'Override field must be one of:')

    def test_direct_over_4096_unicode_characters_rejected_with_unchanged_state_and_retry(self):
        self._assert_invalid_then_retry('bpm', '音' * 4097, 'Override must be nonblank text of at most 4096 characters')

    def test_direct_valid_bpm_invalidates_graph_and_allows_republication(self):
        self.writer.set_override(self.track, 'bpm', '122')
        self.assertEqual(dict(self.peer.read_track(self.track).overrides)['bpm'], '122')
        self._assert_graph_invalidated()
        retry = self._publish('valid-control-retry')
        self.assertNotIn(retry, (self.historical_id, self.current_id))
        self.assertEqual(self.peer.current_graph_snapshot(1, self.peer.source_revision())['build_id'], retry)

    def test_direct_exact_4096_unicode_characters_roundtrip_and_invalidate_graph(self):
        value = '音' * 4096
        self.assertGreater(len(value.encode('utf-8')), 4096)
        validate_override('bpm', value)
        self.writer.set_override(self.track, 'bpm', value)
        self.assertEqual(dict(self.peer.read_track(self.track).overrides)['bpm'], value)
        self._assert_graph_invalidated()

    def test_direct_none_reset_deletes_existing_graph_override_and_invalidates_graph(self):
        self.writer.set_override(self.track, 'bpm', None)
        self.assertNotIn('bpm', dict(self.peer.read_track(self.track).overrides))
        self._assert_graph_invalidated()

    def test_direct_instruments_unicode_override_and_reset_preserve_warm_graph(self):
        before = self._dump()
        value = '音' * 4096
        self.writer.set_override(self.track, 'instruments', value)
        self.assertEqual(dict(self.peer.read_track(self.track).overrides)['instruments'], value)
        self._assert_ready()
        self.assertEqual(self._retained_graph_rows(), self.history)
        self.writer.set_override(self.track, 'instruments', None)
        self.assertNotIn('instruments', dict(self.peer.read_track(self.track).overrides))
        self._assert_ready()
        self.assertEqual(self._dump(), before)
        self.writer.set_override(self.track, 'instruments', None)
        self.assertEqual(self._dump(), before)


if __name__ == '__main__':
    unittest.main()
