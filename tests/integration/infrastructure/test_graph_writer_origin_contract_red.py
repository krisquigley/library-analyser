"""Writer-origin regressions for the already-persisted graph fingerprint contract.

Empty fingerprints are rejected by the existing persisted-row validator. These
public writes must reject them before commit, rather than poison the next writer.
"""
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from music_analyzer.application.dto.analysis import AnalysisError
from music_analyzer.application.dto.catalogue import Inventory, ScannedFile, TrackMetadata
from music_analyzer.domain.catalogue import FileIdentity
from music_analyzer.domain.projection import ProjectionEdge
from music_analyzer.infrastructure.persistence.analysis import SQLiteAnalysisRepository


class GraphWriterOriginContractTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / 'analysis.sqlite'
        self.writer = SQLiteAnalysisRepository(str(self.path))
        self.peer = SQLiteAnalysisRepository(str(self.path))
        files = tuple(
            ScannedFile(
                f'/synthetic/{suffix}.flac', FileIdentity(suffix * 64, 123), 1, 'flac',
                TrackMetadata(duration_seconds=180.0, duration_source='mutagen'),
            )
            for suffix in ('a', 'b', 'c')
        )
        self.writer.register(Inventory('/synthetic', files, (), True))
        a, b, c = (item.identity.track_id for item in files)
        self.full = (ProjectionEdge(a, b, 0.25, 2), ProjectionEdge(b, c, 0.5, 2))
        self.positioned = (ProjectionEdge(a, b, 0.25, 2),)
        # A different valid proposal ensures a bad replacement cannot hide a
        # partial full/positioned mirror update behind identical edge content.
        self.replacement_full = (ProjectionEdge(a, c, 0.75, 2),)
        self.replacement_positioned = self.replacement_full
        self.revision = self.writer.source_revision()
        self.historical_id = self._replace('historical-fingerprint')
        self.current_id = self._replace('current-fingerprint')
        self.assertEqual(self.peer.current_graph_snapshot(2, self.revision)['build_id'], self.current_id)

    def _replace(self, fingerprint, attempt_id=None):
        return self.writer.replace_graph_snapshot(
            self.full, 2, fingerprint, positioned_edges=self.positioned,
            source_revision=self.revision, attempt_id=attempt_id,
        )

    def _database_bytes(self):
        # Compare every persisted value, including timestamps, UUIDs, current
        # pointer, both mirrors, positioned counts and retained history. This
        # is a byte-for-byte logical SQLite dump, not physical page layout.
        # Connections are short-lived; public repositories do not retain one.
        with closing(sqlite3.connect(self.path)) as db:
            return '\n'.join(db.iterdump()).encode('utf-8')

    def _assert_previous_current(self):
        status = self.peer.current_graph_snapshot(2, self.revision)
        self.assertEqual(status['state'], 'ready')
        self.assertEqual(status['build_id'], self.current_id)

    def test_valid_nonempty_fingerprint_roundtrips_for_sparse_zero_edge_publication(self):
        fingerprint = 'valid-zero-edge-fingerprint'
        build_id = self.writer.replace_graph_snapshot(
            (), 2, fingerprint, positioned_edges=(), source_revision=self.revision,
        )
        status = self.peer.current_graph_snapshot(2, self.revision)
        self.assertEqual(status['state'], 'ready')
        self.assertEqual(status['build_id'], build_id)
        self.assertEqual(status['edge_count'], 0)
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(
                db.execute(
                    'SELECT status,source_fingerprint,edge_count,is_current FROM graph_builds WHERE id=?',
                    (build_id,),
                ).fetchone(),
                ('completed', fingerprint, 0, 1),
            )
            self.assertEqual(db.execute('SELECT count(*) FROM graph_edges').fetchone()[0], 0)
            self.assertEqual(db.execute('SELECT count(*) FROM graph_positioned_edges').fetchone()[0], 0)
            self.assertEqual(db.execute('SELECT edge_count FROM graph_build_positioned_snapshots WHERE build_id=?', (build_id,)).fetchone()[0], 0)
            self.assertEqual(db.execute('SELECT count(*) FROM graph_build_edges WHERE build_id=?', (build_id,)).fetchone()[0], 0)
            self.assertEqual(db.execute('SELECT count(*) FROM graph_build_positioned_edges WHERE build_id=?', (build_id,)).fetchone()[0], 0)
            self.assertEqual(db.execute('SELECT count(*) FROM graph_builds WHERE is_current=1').fetchone()[0], 1)
            self.assertEqual(db.execute('SELECT count(*) FROM graph_build_edges WHERE build_id=?', (self.historical_id,)).fetchone()[0], len(self.full))
            self.assertEqual(db.execute('SELECT count(*) FROM graph_build_positioned_edges WHERE build_id=?', (self.historical_id,)).fetchone()[0], len(self.positioned))

    def test_begin_rejects_empty_revision_placeholder_without_changing_publication(self):
        before = self._database_bytes()
        with self.assertRaisesRegex(AnalysisError, 'Graph source fingerprint must be nonempty text'):
            self.writer.begin_graph_build(2, '')
        self.assertEqual(self._database_bytes(), before)
        self.assertEqual(self.peer.source_revision(), self.revision)
        self._assert_previous_current()
        retry_id = self.writer.begin_graph_build(2, self.revision)
        self.assertIsNotNone(retry_id)
        self.assertEqual(self._replace('valid-begin-retry', retry_id), retry_id)
        self.assertEqual(self.peer.current_graph_snapshot(2, self.revision)['build_id'], retry_id)

    def test_begin_rejects_empty_revision_and_preserves_prior_attempt_for_retry(self):
        attempt_id = self.writer.begin_graph_build(2, self.revision)
        self.assertIsNotNone(attempt_id)
        before = self._database_bytes()
        with self.assertRaisesRegex(AnalysisError, 'Graph source fingerprint must be nonempty text'):
            self.peer.begin_graph_build(2, '')
        self.assertEqual(self._database_bytes(), before)
        self._assert_previous_current()
        self.assertIsNone(self.peer.begin_graph_build(2, self.revision))
        self.assertEqual(self._database_bytes(), before)
        self.writer.finish_graph_build_attempt(attempt_id, 'failed', 'safe retry')
        retry_id = self.peer.begin_graph_build(2, self.revision)
        self.assertIsNotNone(retry_id)
        self.assertNotEqual(retry_id, attempt_id)
        self.assertEqual(self._replace('valid-begin-owned-retry', retry_id), retry_id)
        self.assertEqual(self.peer.current_graph_snapshot(2, self.revision)['build_id'], retry_id)

    def test_begin_preserves_normalized_nonempty_opaque_revision_contract(self):
        for revision in (None, False, 0, ' ', 'opaque-revision'):
            with self.subTest(revision=revision):
                attempt_id = self.writer.begin_graph_build(2, revision)
                self.assertIsNotNone(attempt_id)
                with closing(sqlite3.connect(self.path)) as db:
                    self.assertEqual(
                        db.execute(
                            'SELECT source_fingerprint,source_revision FROM graph_builds WHERE id=?',
                            (attempt_id,),
                        ).fetchone(),
                        (str(revision), str(revision)),
                    )
                self.writer.finish_graph_build_attempt(attempt_id, 'failed', 'opaque control')
                self._assert_previous_current()

    def test_direct_replacement_rejects_empty_fingerprint_without_changing_publication(self):
        before = self._database_bytes()
        with self.assertRaises(AnalysisError, msg='direct graph replacement must reject the persisted empty fingerprint contract'):
            self.writer.replace_graph_snapshot(
                self.replacement_full, 2, '', positioned_edges=self.replacement_positioned,
                source_revision=self.revision,
            )
        self.assertEqual(self._database_bytes(), before)
        self._assert_previous_current()
        retry_id = self._replace('valid-direct-retry')
        self.assertNotIn(retry_id, (self.historical_id, self.current_id))
        self.assertEqual(self.peer.current_graph_snapshot(2, self.revision)['build_id'], retry_id)

    def test_attempt_promotion_rejects_empty_fingerprint_and_preserves_owner_for_retry(self):
        attempt_id = self.writer.begin_graph_build(2, self.revision)
        self.assertIsNotNone(attempt_id)
        self.assertIsNone(self.peer.begin_graph_build(2, self.revision))
        before = self._database_bytes()
        with self.assertRaises(AnalysisError, msg='attempt promotion must reject the persisted empty fingerprint contract'):
            self.writer.replace_graph_snapshot(
                self.replacement_full, 2, '', positioned_edges=self.replacement_positioned,
                source_revision=self.revision, attempt_id=attempt_id,
            )
        self.assertEqual(self._database_bytes(), before)
        self._assert_previous_current()
        self.assertIsNone(self.peer.begin_graph_build(2, self.revision))
        self.assertEqual(self._database_bytes(), before)
        self.assertEqual(self._replace('valid-attempt-retry', attempt_id), attempt_id)
        self.assertEqual(self.peer.current_graph_snapshot(2, self.revision)['build_id'], attempt_id)
        completed = self._database_bytes()
        with self.assertRaises(AnalysisError):
            self._replace('late-second-promotion', attempt_id)
        self.assertEqual(self._database_bytes(), completed)
        with self.assertRaises(AnalysisError):
            self.writer.finish_graph_build_attempt(attempt_id, 'failed', 'late failure')
        self.assertEqual(self._database_bytes(), completed)

    def test_final_positioned_fk_failure_rolls_back_and_same_attempt_retries(self):
        """P7 characterization: late positioned INSERT cannot partially publish."""
        attempt_id = self.writer.begin_graph_build(2, self.revision)
        self.assertIsNotNone(attempt_id)
        before = self._database_bytes()
        missing = 'sha256:' + 'f' * 64
        invalid_last = ProjectionEdge(self.full[0].a, missing, 0.5, 2)
        with self.assertRaisesRegex(AnalysisError, 'FOREIGN KEY constraint failed'):
            self.writer.replace_graph_snapshot(
                self.replacement_full, 2, 'late-positioned-fk',
                positioned_edges=(*self.positioned, invalid_last),
                source_revision=self.revision, attempt_id=attempt_id,
            )
        self.assertEqual(self._database_bytes(), before)
        self._assert_previous_current()
        self.assertEqual(self._replace('corrected-positioned-retry', attempt_id), attempt_id)
        self.assertEqual(self.peer.current_graph_snapshot(2, self.revision)['build_id'], attempt_id)
        completed = self._database_bytes()
        with self.assertRaises(AnalysisError):
            self._replace('late-repromotion', attempt_id)
        self.assertEqual(self._database_bytes(), completed)

    def test_failure_record_rejects_empty_fingerprint_without_changing_current_or_attempt(self):
        attempt_id = self.writer.begin_graph_build(2, self.revision)
        self.assertIsNotNone(attempt_id)
        before = self._database_bytes()
        with self.assertRaises(AnalysisError, msg='failure recording must reject the persisted empty fingerprint contract'):
            self.writer.record_graph_failure(2, '', 'synthetic failure', source_revision=self.revision)
        self.assertEqual(self._database_bytes(), before)
        self._assert_previous_current()
        self.assertIsNone(self.peer.begin_graph_build(2, self.revision))
        self.assertEqual(self._database_bytes(), before)
        self.writer.record_graph_failure(2, 'valid-failure-fingerprint', 'synthetic failure', source_revision=self.revision)
        self._assert_previous_current()
        self.assertIsNone(self.peer.begin_graph_build(2, self.revision))
        self.writer.finish_graph_build_attempt(attempt_id, 'failed', 'retryable attempt failure')
        failed = self._database_bytes()
        self.writer.finish_graph_build_attempt(attempt_id, 'failed', 'idempotent late detail')
        self.assertEqual(self._database_bytes(), failed)
        retry_id = self.peer.begin_graph_build(2, self.revision)
        self.assertIsNotNone(retry_id)
        self.assertNotEqual(retry_id, attempt_id)
        fenced = self._database_bytes()
        with self.assertRaises(AnalysisError):
            self._replace('late-failed-attempt-promotion', attempt_id)
        self.assertEqual(self._database_bytes(), fenced)
        self.assertEqual(self._replace('valid-failure-retry', retry_id), retry_id)


if __name__ == '__main__':
    unittest.main()
