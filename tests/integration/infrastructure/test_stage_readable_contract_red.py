"""Retained stage text must be readable before the originating public save commits."""
from contextlib import closing
from dataclasses import asdict
from pathlib import Path
import sqlite3
import tempfile
import unittest

from music_analyzer.application.dto.analysis import AnalysisError, AudioSource, StageResult
from music_analyzer.application.dto.catalogue import Inventory, ScannedFile, TrackMetadata
from music_analyzer.domain.analysis import ScoreSummary, ScoreWindow
from music_analyzer.domain.catalogue import FileIdentity
from music_analyzer.domain.projection import ProjectionEdge
from music_analyzer.infrastructure.persistence.analysis import SQLiteAnalysisRepository
from music_analyzer.infrastructure.persistence.stage_mapping import stage_from_mapping


class StageReadableContractRedTests(unittest.TestCase):
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
        identity, other = self.identities
        self.other_run = self.repository.start(AudioSource('/music/other.flac', other.track_id))
        for stage in (StageResult('bpm', (), '', (('bpm', 124.0),)),
                      StageResult('key', (), '', (('key', '8A'),)),
                      StageResult('genres', (), ''), StageResult('mood', (), ''),
                      StageResult('energy', (), '')):
            self.repository.save_stage(self.other_run, stage)
        self.repository.finish(self.other_run, 'completed', '')
        self.run_id = self.repository.start(AudioSource('/music/song.flac', identity.track_id))
        edges = (ProjectionEdge(identity.track_id, other.track_id, 0.25, 2),)
        self.build_id = self.repository.replace_graph_snapshot(
            edges, 10, 'source-fp', positioned_edges=edges)

    def _publication_state(self):
        # Full small rows, including stage payloads and both current/history
        # graph projections. Snapshot AFTER start so intentional start effects
        # cannot be confused with effects of the rejected save.
        tables = ('runs', 'run_tracks', 'stages', 'graph_feature_evidence',
                  'graph_builds', 'graph_edges', 'graph_positioned_edges',
                  'graph_build_edges', 'graph_build_positioned_edges',
                  'graph_build_positioned_snapshots')
        with closing(sqlite3.connect(self.path)) as db:
            return tuple((table, tuple(db.execute(f'SELECT * FROM {table} ORDER BY rowid')))
                         for table in tables)

    def _assert_rejected_at_save_and_retry(self, malformed):
        # Establish the actual reader contract independently: these DTOs are
        # constructible/JSON-serializable but their retained mappings are not
        # readable. Do not wait for finish or a poisoned read to reject them.
        with self.assertRaises(ValueError):
            stage_from_mapping(asdict(malformed))
        self.assertEqual(self.repository.current_graph_snapshot(
            10, self.repository.source_revision())['state'], 'ready')
        before = self._publication_state()
        with self.assertRaisesRegex(AnalysisError, r'(?i)(stage|text|provenance|uncertainty)'):
            self.repository.save_stage(self.run_id, malformed)
        self.assertEqual(self._publication_state(), before,
                         'Rejected save must preserve whole run/stages/evidence and current/history graph')
        stored = self.repository.read_track(self.identities[0].track_id)
        self.assertEqual((stored.run.run_id, stored.run.status, stored.run.stages),
                         (self.run_id, 'running', ()))
        self.assertEqual(self.repository.current_graph_snapshot(
            10, self.repository.source_revision())['state'], 'ready')
        valid = StageResult('instruments', (('source', 'synthetic'),), 'valid retry',
                            (('instrument', 'piano'), ('confidence', 0.75)))
        self.repository.save_stage(self.run_id, valid)
        self.assertEqual(self.repository.read_track(self.identities[0].track_id).run.stages, (valid,))
        self.repository.finish(self.run_id, 'completed', '')
        self.assertEqual(self.repository.read_track(self.identities[0].track_id).run.status, 'completed')

    def test_save_stage_rejects_nontext_uncertainty_without_commit_and_same_stage_retries(self):
        self._assert_rejected_at_save_and_retry(StageResult('instruments', (), 123))

    def test_save_stage_rejects_nontext_provenance_without_commit_and_same_stage_retries(self):
        self._assert_rejected_at_save_and_retry(StageResult('instruments', (('source', 123),), ''))

    def test_valid_producer_shapes_remain_readable_through_public_save(self):
        # Independently runnable on the RED base. Numeric VALUES remain allowed;
        # numeric provenance is different. No new stage-name enum or required
        # summary: empty outputs and legacy summary-only payloads stay readable.
        stages = (
            StageResult('instruments', (('source', 'synthetic'),), 'uncertain',
                        (('instrument', 'piano'), ('confidence', 0.75), ('count', 2))),
            StageResult('bpm', (), '', (('bpm', 'fast'),)),
            StageResult('genres', (), ''),
            StageResult('mood', (), '', summary=ScoreSummary(
                ('happy',), (0.7,), (0.7,), (0.7,), 1.0)),
            StageResult('energy', (), '', windows=(ScoreWindow(0.0, 1.0, (0.7,)),),
                        summary=ScoreSummary(('high',), (0.7,), (0.7,), (0.7,), 1.0),
                        raw_predictions=(((0.7,),),)),
        )
        for stage in stages:
            with self.subTest(stage=stage.stage):
                self.assertEqual(stage_from_mapping(asdict(stage)), stage)
                self.repository.save_stage(self.run_id, stage)
                self.assertIn(stage, self.repository.read_track(self.identities[0].track_id).run.stages)
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute('SELECT status FROM runs WHERE id=?',
                                        (self.run_id,)).fetchone(), ('running',))
            self.assertEqual(db.execute('SELECT run_id FROM graph_feature_evidence WHERE is_current=1')
                             .fetchall(), [(self.other_run,)])
            self.assertEqual(db.execute('SELECT count(*) FROM graph_build_edges WHERE build_id=?',
                                        (self.build_id,)).fetchone(), (1,))
            self.assertEqual(db.execute('SELECT count(*) FROM graph_build_positioned_edges WHERE build_id=?',
                                        (self.build_id,)).fetchone(), (1,))
