"""Public finish must bound aggregate compact evidence, not just each stage.

Synthetic UTF-8 text only; at most two tracks, sequential temporary databases,
and no raw-SQL fixture mutation. Run this module under a hard 120s timeout.
"""
from contextlib import closing
from dataclasses import asdict, replace
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from music_analyzer.application.dto.analysis import AnalysisError, AudioSource
from music_analyzer.application.use_cases.graph_feature_evidence import (
    build_graph_feature_evidence, validate_graph_feature_evidence_payload,
)
from music_analyzer.application.dto.catalogue import Inventory, ScannedFile, TrackMetadata
from music_analyzer.domain.catalogue import FileIdentity
from music_analyzer.domain.projection import ProjectionEdge
from music_analyzer.infrastructure.persistence.analysis import SQLiteAnalysisRepository
from music_analyzer.infrastructure.persistence.explorer_readonly import ReadOnlyExplorerSQLiteRepository
from music_explorer.infrastructure.explorer_readonly import (
    AnalysisError as StandaloneAnalysisError,
    ReadOnlyExplorerSQLiteRepository as StandaloneReadOnlyExplorerSQLiteRepository,
)
from tests.integration.infrastructure.test_graph_feature_evidence_red import (
    _graph_relevant_stages,
)


BYTE_LIMIT = 16 * 1024 * 1024
SCRATCH_LIMIT = 512 * 1024 * 1024


def _stage_bytes(stage):
    return len(json.dumps(asdict(stage), allow_nan=False, ensure_ascii=False).encode('utf-8'))


def _stages_at_evidence_size(track_id, run_id, target):
    stages = _graph_relevant_stages()
    empty = tuple(replace(stage, uncertainty='') for stage in stages)
    overhead = len(build_graph_feature_evidence(track_id, run_id, empty).payload_json().encode('utf-8'))
    remaining = target - overhead
    assert remaining >= 0
    quotient, remainder = divmod(remaining, len(empty))
    return tuple(replace(stage, uncertainty='é' * ((quotient + (index < remainder)) // 2)
                         + 'x' * ((quotient + (index < remainder)) % 2))
                 for index, stage in enumerate(empty))


class GraphFeatureEvidenceAggregateFinishRedTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='aggregate-finish-')
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'analysis.sqlite'
        self.repository = SQLiteAnalysisRepository(str(self.path))
        self._register_tracks()

    def _register_tracks(self):
        self.identities = (FileIdentity('a' * 64, 123), FileIdentity('b' * 64, 123))
        self.repository.register(Inventory('/music', tuple(
            ScannedFile(location, identity, 1, 'flac',
                        TrackMetadata(duration_seconds=180.0, duration_source='mutagen'))
            for location, identity in zip(('/music/song.flac', '/music/other.flac'), self.identities)
        ), (), True))

    def _assert_scratch_bound(self):
        self.assertLessEqual(sum(path.stat().st_size for path in self.path.parent.rglob('*')
                                 if path.is_file()), SCRATCH_LIMIT)

    def _publication_digest(self):
        # Full logical transaction state, including stage bytes, lifecycle,
        # current/full/positioned mirrors and all graph history. Hash one dump
        # line at a time; failure output never contains retained payload text.
        digest = hashlib.sha256()
        with closing(sqlite3.connect(self.path)) as db:
            for line in db.iterdump():
                digest.update(line.encode('utf-8'))
                digest.update(b'\n')
        self._assert_scratch_bound()
        return digest.hexdigest()

    def _start(self, index=0):
        location = ('/music/song.flac', '/music/other.flac')[index]
        return self.repository.start(AudioSource(location, self.identities[index].track_id))

    def _save_valid_stages(self, run_id, stages, target=None, index=0):
        self.assertEqual(len(stages), 5)
        for stage in stages:
            self.assertLess(_stage_bytes(stage), BYTE_LIMIT)
            self.repository.save_stage(run_id, stage)
        evidence = build_graph_feature_evidence(self.identities[index].track_id, run_id, stages)
        validate_graph_feature_evidence_payload(evidence.track_id, run_id, evidence.fingerprint, evidence.payload)
        size = len(evidence.payload_json().encode('utf-8'))
        if target is not None:
            self.assertEqual(size, target)
        with closing(sqlite3.connect(self.path)) as db:
            sizes = tuple(row[0] for row in db.execute(
                'SELECT length(CAST(result AS BLOB)) FROM stages WHERE run_id=?', (run_id,)))
            self.assertEqual(len(sizes), 5)
            self.assertTrue(all(0 < size < BYTE_LIMIT for size in sizes))
        self._assert_scratch_bound()
        return size

    def _assert_public_reads(self):
        expected = tuple(identity.track_id for identity in self.identities)
        self.assertEqual(ReadOnlyExplorerSQLiteRepository(str(self.path)).track_ids(), expected)
        self.assertEqual(StandaloneReadOnlyExplorerSQLiteRepository(str(self.path)).track_ids(), expected)

    def test_small_valid_five_stage_finish_control(self):
        run_id = self._start()
        self.assertLess(self._save_valid_stages(run_id, _graph_relevant_stages()), BYTE_LIMIT)
        self.repository.finish(run_id, 'completed', '')
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute('SELECT status FROM runs WHERE id=?', (run_id,)).fetchone(), ('completed',))
            self.assertEqual(db.execute('SELECT run_id FROM graph_feature_evidence WHERE is_current=1').fetchall(), [(run_id,)])
        self._assert_public_reads()

    def test_finish_accepts_exact_and_one_byte_under_multibyte_aggregate_limit(self):
        for target in (BYTE_LIMIT - 1, BYTE_LIMIT):
            with self.subTest(evidence_bytes=target), tempfile.TemporaryDirectory(prefix='aggregate-boundary-') as scratch:
                # Separate histories and cleanup before exercising the next limit.
                old_path, old_repository = self.path, self.repository
                try:
                    self.path = Path(scratch) / 'analysis.sqlite'
                    self.repository = SQLiteAnalysisRepository(str(self.path))
                    self._register_tracks()
                    run_id = self._start()
                    stages = _stages_at_evidence_size(self.identities[0].track_id, run_id, target)
                    self._save_valid_stages(run_id, stages, target)
                    del stages
                    self.repository.finish(run_id, 'completed', '')
                    with closing(sqlite3.connect(self.path)) as db:
                        self.assertEqual(db.execute('SELECT length(CAST(evidence_json AS BLOB)) FROM graph_feature_evidence WHERE run_id=?', (run_id,)).fetchone(), (target,))
                        self.assertEqual(db.execute('SELECT status FROM runs WHERE id=?', (run_id,)).fetchone(), ('completed',))
                    self.assertLessEqual(sum(p.stat().st_size for p in Path(scratch).rglob('*') if p.is_file()), SCRATCH_LIMIT)
                    self._assert_public_reads()
                finally:
                    self.path, self.repository = old_path, old_repository

    def test_finish_rejects_oversized_aggregate_atomically_preserves_running_candidate_and_valid_retry(self):
        prior_run = self._start()
        self._save_valid_stages(prior_run, _graph_relevant_stages())
        self.repository.finish(prior_run, 'completed', '')
        other_run = self._start(1)
        self._save_valid_stages(other_run, _graph_relevant_stages(), index=1)
        self.repository.finish(other_run, 'completed', '')
        run_id = self._start()
        # Five individually readable ~3.5 MiB retained stages, not an oversized
        # single stage or malformed generated evidence. Unicode checks bytes.
        stages = tuple(replace(stage, uncertainty='é' * (7 * 1024 * 1024 // 4))
                       for stage in _graph_relevant_stages())
        expected_size = self._save_valid_stages(run_id, stages)
        del stages
        self.assertGreater(expected_size, BYTE_LIMIT)
        edges = (ProjectionEdge(self.identities[0].track_id, self.identities[1].track_id, 0.25, 2),)
        build_id = self.repository.replace_graph_snapshot(edges, 10, 'aggregate-control', positioned_edges=edges)
        self.assertEqual(self.repository.current_graph_snapshot(10, self.repository.source_revision())['state'], 'ready')
        before = self._publication_digest()  # AFTER start and all checkpoints.
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute('SELECT status FROM runs WHERE id=?', (run_id,)).fetchone(), ('running',))
            self.assertEqual(db.execute('SELECT run_id FROM graph_feature_evidence WHERE is_current=1').fetchall(), [(other_run,)])
            self.assertEqual(db.execute('SELECT is_current FROM graph_builds WHERE id=?', (build_id,)).fetchone(), (1,))
        try:
            self.repository.finish(run_id, 'completed', '')
        except AnalysisError as error:
            self.assertRegex(str(error), r'(?i)(evidence|feature|size|bytes|16\s*mi?b)')
        else:
            with closing(sqlite3.connect(self.path)) as db:
                actual = db.execute('SELECT length(CAST(evidence_json AS BLOB)) FROM graph_feature_evidence WHERE run_id=?', (run_id,)).fetchone()
            self.assertEqual(actual, (expected_size,), 'Baseline must reach the intended aggregate publication, not an incidental fixture failure')
            self._assert_scratch_bound()
            # Baseline proof: public writer committed bytes that both public
            # readers reject. These checks are not the desired finish behavior.
            with self.assertRaises(AnalysisError):
                ReadOnlyExplorerSQLiteRepository(str(self.path)).track_ids()
            with self.assertRaises(StandaloneAnalysisError):
                StandaloneReadOnlyExplorerSQLiteRepository(str(self.path)).track_ids()
            self.fail(f'AnalysisError not raised: finish committed aggregate evidence bytes={actual}; limit={BYTE_LIMIT}; both full readers rejected')
        self.assertEqual(self._publication_digest(), before, 'Rejected finish must roll back every logical table')
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute('SELECT status FROM runs WHERE id=?', (run_id,)).fetchone(), ('running',))
            self.assertEqual(db.execute('SELECT count(*) FROM graph_feature_evidence WHERE run_id=?', (run_id,)).fetchone(), (0,))
            self.assertEqual(db.execute('SELECT status FROM runs WHERE id=?', (prior_run,)).fetchone(), ('completed',))
        self.assertEqual(self.repository.current_graph_snapshot(10, self.repository.source_revision())['state'], 'ready')
        # Immutable checkpoints cannot be replaced. Retry via a fresh public
        # candidate; the rejected candidate must still be running and retained.
        retry = self._start()
        self._save_valid_stages(retry, _graph_relevant_stages())
        self.repository.finish(retry, 'completed', '')
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute('SELECT status FROM runs WHERE id=?', (retry,)).fetchone(), ('completed',))
            self.assertEqual(db.execute('SELECT status FROM runs WHERE id=?', (run_id,)).fetchone(), ('running',))
            self.assertEqual({row[0] for row in db.execute('SELECT run_id FROM graph_feature_evidence WHERE is_current=1')}, {retry, other_run})
        self._assert_public_reads()
        self._assert_scratch_bound()
