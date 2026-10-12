"""RAW/WINDOW checkpoints must be readable before the originating save commits.

Only public repository APIs write/read this bounded two-track catalogue. Opaque
file equality additionally protects retained history/evidence not exposed by a
public row API; no SQL or private repository connections are used here.
"""
from dataclasses import asdict
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from music_analyzer.application.dto.analysis import AnalysisError, AudioSource, StageResult
from music_analyzer.application.dto.catalogue import Inventory, ScannedFile, TrackMetadata
from music_analyzer.domain.analysis import ScoreSummary, ScoreWindow
from music_analyzer.domain.catalogue import FileIdentity
from music_analyzer.domain.projection import ProjectionEdge
from music_analyzer.infrastructure.persistence.analysis import SQLiteAnalysisRepository
from music_analyzer.infrastructure.persistence.stage_mapping import stage_from_mapping
from music_explorer.infrastructure.explorer_readonly import ReadOnlyExplorerSQLiteRepository


class StageRawWindowWriterContractRedTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / 'analysis.sqlite'
        self.writer = SQLiteAnalysisRepository(str(self.path))
        self.reader = ReadOnlyExplorerSQLiteRepository(str(self.path))
        self.identities = (FileIdentity('a' * 64, 123), FileIdentity('b' * 64, 123))
        self.writer.register(Inventory('/music', tuple(
            ScannedFile(f'/music/{name}.flac', identity, 1, 'flac',
                        TrackMetadata(duration_seconds=180.0, duration_source='mutagen'))
            for name, identity in zip(('candidate', 'other'), self.identities)
        ), (), True))
        self.other_run = self.writer.start(AudioSource('/music/other.flac', self.identities[1].track_id))
        for stage in (StageResult('bpm', (), '', (('bpm', 124.0),)),
                      StageResult('key', (), '', (('key', '8A'),)),
                      StageResult('genres', (), ''), StageResult('mood', (), ''),
                      StageResult('energy', (), '')):
            self.writer.save_stage(self.other_run, stage)
        self.writer.finish(self.other_run, 'completed', '')
        self.run_id = self.writer.start(AudioSource('/music/candidate.flac', self.identities[0].track_id))
        self.revision = self.writer.source_revision()
        edges = (ProjectionEdge(self.identities[0].track_id, self.identities[1].track_id, 0.25, 2),)
        # Warm AFTER start, which intentionally invalidates earlier publication.
        # Keep a distinct historical full/positioned snapshot as well as current.
        historical_edges = (ProjectionEdge(self.identities[0].track_id, self.identities[1].track_id, 0.5, 2),)
        self.historical_id = self.writer.replace_graph_snapshot(
            historical_edges, 10, 'historical', positioned_edges=historical_edges,
            source_revision=self.revision)
        self.build_id = self.writer.replace_graph_snapshot(
            edges, 10, 'current', positioned_edges=edges, source_revision=self.revision)
        self.assertNotEqual(self.historical_id, self.build_id)
        self.assertEqual(self.writer.current_graph_snapshot(10, self.revision)['state'], 'ready')
        self.assertEqual(len(self.reader.current_graph_edges(10)[1]), 1)
        self.assertEqual(len(self.reader.current_positioned_graph_edges(10)[1]), 1)

    def _public_state(self):
        return (
            tuple(self.writer.read_track(identity.track_id) for identity in self.identities),
            self.writer.source_revision(),
            self.writer.current_graph_snapshot(10, self.revision),
            self.reader.candidate_snapshot(),
            self.reader.current_graph_edges(10),
            self.reader.current_positioned_graph_edges(10),
            self.reader.mood_axis_graph_snapshot(sparse_k=10),
        )

    @staticmethod
    def _valid_scores():
        windows = (ScoreWindow(0.0, 1.0, (0.7,)),)
        summary = ScoreSummary(('happy',), (0.7,), (0.7,), (0.7,), 1.0)
        return StageResult('mood', (('source', 'synthetic'),), '', windows=windows,
                           summary=summary, raw_predictions=(((0.7,),),))

    def _valid_same_run_stage_retry(self):
        valid = self._valid_scores()
        self.assertEqual(stage_from_mapping(json.loads(json.dumps(asdict(valid)))), valid)
        self.writer.save_stage(self.run_id, valid)
        report = self.writer.read_track(self.identities[0].track_id)
        self.assertEqual((report.run.run_id, report.run.status, report.run.stages),
                         (self.run_id, 'running', (valid,)))
        self.writer.finish(self.run_id, 'completed', '')
        report = self.writer.read_track(self.identities[0].track_id)
        self.assertEqual((report.run.run_id, report.run.status, report.run.stages),
                         (self.run_id, 'completed', (valid,)))
        self.assertEqual(self.writer.read_track(self.identities[1].track_id).run.run_id, self.other_run)
        # Public compact reading also exercises evidence after valid publication.
        self.reader.mood_axis_graph_snapshot(sparse_k=10)

    def _assert_origin_rejection_and_retry(self, malformed, reader_message):
        # Real DTO construction and strict JSON succeed; the actual reader then
        # rejects the retained mapping. NaN/Inf are not gaps in this writer.
        payload = json.dumps(asdict(malformed), allow_nan=False)
        with self.assertRaisesRegex(ValueError, reader_message):
            stage_from_mapping(json.loads(payload))
        before = self._public_state()
        before_bytes = self.path.read_bytes()
        with patch('sqlite3.connect', wraps=sqlite3.connect) as connect:
            with self.assertRaisesRegex(AnalysisError, r'(?i)(stage|raw|score|window)'):
                self.writer.save_stage(self.run_id, malformed)
            connect.assert_not_called()  # Validation belongs before the transaction.
        self.assertEqual(self.path.read_bytes(), before_bytes,
                         'Rejected save must preserve all retained runs/stages/evidence and graph history')
        self.assertEqual(self._public_state(), before,
                         'Rejected save must not invalidate either current graph mirror')
        self.assertEqual(self.writer.current_graph_snapshot(10, self.revision)['build_id'], self.build_id)
        self._valid_same_run_stage_retry()

    def test_save_rejects_nonnumeric_raw_score_before_transaction_and_same_stage_retries(self):
        self._assert_origin_rejection_and_retry(
            StageResult('mood', (), '', raw_predictions=((('not-a-score',),),)),
            'Invalid raw scores')

    def test_save_rejects_negative_window_start_before_transaction_and_same_stage_retries(self):
        valid = self._valid_scores()
        self._assert_origin_rejection_and_retry(
            StageResult('mood', (), '', windows=(ScoreWindow(-1.0, 1.0, (0.7,)),),
                        summary=valid.summary),
            'Invalid score shape, score, or coverage window')

    def test_existing_text_rejection_reaches_rollback_and_same_stage_retry_assertions(self):
        # Existing inward text policy provides a real rejection, not a patched
        # save/validator. Run every rollback/graph/history assertion and retry
        # on the unmodified baseline while RAW/WINDOW assertions remain RED.
        self._assert_origin_rejection_and_retry(StageResult('mood', (), 123), 'Invalid stage text')

    def test_valid_same_run_stage_retry_path_is_reachable_on_baseline(self):
        # Independent green control: the post-rejection path must not hide a
        # fixture, graph/evidence, producer-shape or lifecycle failure.
        self._valid_same_run_stage_retry()

    def test_valid_producer_optional_and_legacy_shapes_remain_readable(self):
        stages = (
            StageResult('instruments', (), 'optional empty scores'),
            StageResult('bpm', (), '', (('bpm', 'fast'),)),
            StageResult('energy', (), '', raw_predictions=(((0.2, 0.7),),)),
            StageResult('genres', (), '', summary=ScoreSummary(
                ('ambient',), (0.7,), (0.7,), (0.7,), 1.0)),
            self._valid_scores(),
        )
        for stage in stages:
            with self.subTest(stage=stage.stage):
                self.assertEqual(stage_from_mapping(json.loads(json.dumps(asdict(stage)))), stage)
                self.writer.save_stage(self.run_id, stage)
                self.assertIn(stage, self.writer.read_track(self.identities[0].track_id).run.stages)
        self.assertEqual(self.writer.read_track(self.identities[0].track_id).run.status, 'running')


if __name__ == '__main__':
    unittest.main()
