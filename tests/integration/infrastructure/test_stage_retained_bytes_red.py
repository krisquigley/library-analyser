"""Public stage writes must not exceed the readers' retained UTF-8 byte limit."""
from contextlib import closing
from dataclasses import asdict, replace
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from music_analyzer.application.dto.analysis import AnalysisError, AudioSource, StageResult
from music_analyzer.application.dto.catalogue import Inventory, ScannedFile, TrackMetadata
from music_analyzer.domain.catalogue import FileIdentity
from music_analyzer.domain.projection import ProjectionEdge
from music_analyzer.infrastructure.persistence.analysis import SQLiteAnalysisRepository


# Existing reader contract: size == 16 MiB is accepted; size > 16 MiB is not.
RETAINED_STAGE_BYTE_LIMIT = 16 * 1024 * 1024


def _serialized_bytes(stage):
    return len(json.dumps(asdict(stage), allow_nan=False, ensure_ascii=False).encode('utf-8'))


def _multibyte_stage_at_limit():
    stage = StageResult('bpm', (), '', (('bpm', 124.0),))
    remaining = RETAINED_STAGE_BYTE_LIMIT - _serialized_bytes(stage)
    # One bounded synthetic multibyte body. ASCII padding makes the exact byte
    # boundary independent of whether the JSON envelope has odd or even size.
    return replace(stage, uncertainty='é' * (remaining // 2) + 'x' * (remaining % 2))


class StageRetainedBytesRedTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'analysis.sqlite'
        self.repository = SQLiteAnalysisRepository(str(self.path))
        self.identities = (FileIdentity('a' * 64, 123), FileIdentity('b' * 64, 123))
        self.repository.register(Inventory('/music', tuple(
            ScannedFile(location, identity, 1, 'flac',
                        TrackMetadata(duration_seconds=180.0, duration_source='mutagen'))
            for location, identity in zip(('/music/song.flac', '/music/other.flac'), self.identities)
        ), (), True))

    def _publication_state(self):
        # Bounded observations of all lifecycle/publication tables. Never dump a
        # 16 MiB payload into failure output or retain a second copy of it.
        tables = ('runs', 'run_tracks', 'graph_feature_evidence', 'graph_builds',
                  'graph_edges', 'graph_positioned_edges', 'graph_build_edges',
                  'graph_build_positioned_edges', 'graph_build_positioned_snapshots')
        with closing(sqlite3.connect(self.path)) as db:
            rows = tuple((table, tuple(db.execute(f'SELECT * FROM {table} ORDER BY rowid')))
                         for table in tables)
            stages = tuple(db.execute(
                'SELECT run_id,stage,length(CAST(result AS BLOB)) FROM stages ORDER BY run_id,stage'))
        return rows, stages

    def _running_candidate_with_warm_graph(self):
        identity, other = self.identities
        # Keep an independent, valid evidence publication and warm graph in place
        # immediately before the rejected graph-relevant checkpoint.
        other_run = self.repository.start(AudioSource('/music/other.flac', other.track_id))
        for stage in (StageResult('bpm', (), '', (('bpm', 124.0),)),
                      StageResult('key', (), '', (('key', '8A'),)),
                      StageResult('genres', (), ''), StageResult('mood', (), ''),
                      StageResult('energy', (), '')):
            self.repository.save_stage(other_run, stage)
        self.repository.finish(other_run, 'completed', '')
        run_id = self.repository.start(AudioSource('/music/song.flac', identity.track_id))
        edges = (ProjectionEdge(identity.track_id, other.track_id, 0.25, 2),)
        build_id = self.repository.replace_graph_snapshot(edges, 10, 'source-fp', positioned_edges=edges)
        return run_id, other_run, build_id

    def test_save_stage_rejects_oversized_multibyte_bytes_before_commit_and_same_run_retries(self):
        run_id, other_run, build_id = self._running_candidate_with_warm_graph()
        before = self._publication_state()
        oversized = _multibyte_stage_at_limit()
        oversized = replace(oversized, uncertainty=oversized.uncertainty + 'x')
        self.assertEqual(_serialized_bytes(oversized), RETAINED_STAGE_BYTE_LIMIT + 1)
        self.assertLess(len(json.dumps(asdict(oversized), ensure_ascii=False)), RETAINED_STAGE_BYTE_LIMIT)

        with self.assertRaisesRegex(AnalysisError, r'(?i)(stage|size|bytes|16\s*mi?b)'):
            self.repository.save_stage(run_id, oversized)

        del oversized
        self.assertEqual(self._publication_state(), before,
                         'Rejected stage must preserve running run, evidence, current graph and history')
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute('SELECT status FROM runs WHERE id=?', (run_id,)).fetchone(), ('running',))
            self.assertEqual(db.execute('SELECT count(*) FROM stages WHERE run_id=?', (run_id,)).fetchone(), (0,))
            self.assertEqual(db.execute('SELECT run_id FROM graph_feature_evidence WHERE is_current=1').fetchall(), [(other_run,)])
            self.assertEqual(db.execute('SELECT is_current FROM graph_builds WHERE id=?', (build_id,)).fetchone(), (1,))
        # Public reads must not expose a poisoned retained running checkpoint.
        stored = self.repository.read_track(self.identities[0].track_id)
        self.assertEqual((stored.run.run_id, stored.run.status, stored.run.stages),
                         (run_id, 'running', ()))
        # Public graph/lifecycle operations must still be usable, not merely
        # raw SQL observations of the rejected checkpoint.
        self.assertEqual(self.repository.current_graph_snapshot(10, self.repository.source_revision())['state'], 'ready')
        valid = StageResult('bpm', (), 'valid retry', (('bpm', 124.0),))
        self.repository.save_stage(run_id, valid)
        self.repository.finish(run_id, 'completed', '')
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute('SELECT status FROM runs WHERE id=?', (run_id,)).fetchone(), ('completed',))
            self.assertEqual(db.execute('SELECT count(*) FROM stages WHERE run_id=?', (run_id,)).fetchone(), (1,))

    def test_small_valid_stage_control_preserves_other_evidence_and_public_lifecycle(self):
        # Independently executable on the RED base: the actual same-run retry
        # after rejection remains asserted in the oversized-stage regression.
        run_id, other_run, build_id = self._running_candidate_with_warm_graph()
        stored = self.repository.read_track(self.identities[0].track_id)
        self.assertEqual((stored.run.run_id, stored.run.status, stored.run.stages),
                         (run_id, 'running', ()))
        self.assertEqual(self.repository.current_graph_snapshot(
            10, self.repository.source_revision())['state'], 'ready')
        valid = StageResult('bpm', (), 'valid retry control', (('bpm', 124.0),))
        self.repository.save_stage(run_id, valid)
        self.repository.finish(run_id, 'completed', '')
        self.repository.source_revision()
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute('SELECT status FROM runs WHERE id=?', (run_id,)).fetchone(), ('completed',))
            self.assertEqual(db.execute('SELECT stage FROM stages WHERE run_id=?', (run_id,)).fetchall(), [('bpm',)])
            self.assertEqual(db.execute('SELECT run_id FROM graph_feature_evidence WHERE is_current=1').fetchall(), [(other_run,)])
            # A valid graph-relevant write intentionally demotes the current
            # graph, but its historical build and edges must remain intact.
            self.assertEqual(db.execute('SELECT status,is_current FROM graph_builds WHERE id=?', (build_id,)).fetchone(), ('completed', 0))
            self.assertEqual(db.execute('SELECT count(*) FROM graph_build_edges WHERE build_id=?', (build_id,)).fetchone(), (1,))

    def test_save_stage_accepts_equal_and_one_byte_under_retained_limit(self):
        equal = _multibyte_stage_at_limit()
        self.assertEqual(_serialized_bytes(equal), RETAINED_STAGE_BYTE_LIMIT)
        # The last padding character may be multibyte; replace its UTF-8 bytes
        # with one fewer ASCII byte to construct exactly limit - 1.
        last_bytes = len(equal.uncertainty[-1].encode('utf-8'))
        under = replace(equal, uncertainty=equal.uncertainty[:-1] + 'x' * (last_bytes - 1))
        del equal
        self.assertEqual(_serialized_bytes(under), RETAINED_STAGE_BYTE_LIMIT - 1)
        for expected_size in (RETAINED_STAGE_BYTE_LIMIT - 1, RETAINED_STAGE_BYTE_LIMIT):
            with self.subTest(serialized_bytes=expected_size), tempfile.TemporaryDirectory() as scratch:
                if expected_size == RETAINED_STAGE_BYTE_LIMIT:
                    under = replace(under, uncertainty=under.uncertainty + 'x')
                # Each control has just one large row and is cleaned before the
                # next boundary is exercised; no accumulating retained history.
                path = Path(scratch) / 'boundary.sqlite'
                repository = SQLiteAnalysisRepository(str(path))
                identity = self.identities[0]
                repository.register(Inventory('/music', (
                    ScannedFile('/music/song.flac', identity, 1, 'flac',
                                TrackMetadata(duration_seconds=180.0, duration_source='mutagen')),
                ), (), True))
                run_id = repository.start(AudioSource('/music/song.flac', identity.track_id))
                repository.save_stage(run_id, under)
                with closing(sqlite3.connect(path)) as db:
                    self.assertEqual(db.execute(
                        'SELECT length(CAST(result AS BLOB)) FROM stages WHERE run_id=?',
                        (run_id,)).fetchone(), (expected_size,))
                    self.assertEqual(db.execute('SELECT status FROM runs WHERE id=?', (run_id,)).fetchone(), ('running',))
