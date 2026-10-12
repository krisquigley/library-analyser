"""Reject boolean numeric checkpoints at public save, not at a later read.

Only two eligible synthetic tracks and a single full/positioned edge are used.
Scanner completeness and score-summary provisional flags are legitimate booleans;
they must not be confused with numeric stage values.
"""
from contextlib import closing
from dataclasses import asdict
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from music_analyzer.application.dto.analysis import AnalysisError, AudioSource, StageResult
from music_analyzer.application.dto.catalogue import Inventory, ScannedFile, TrackMetadata
from music_analyzer.domain.analysis import ScoreSummary
from music_analyzer.domain.catalogue import FileIdentity
from music_analyzer.domain.projection import ProjectionEdge
from music_analyzer.infrastructure.persistence.analysis import SQLiteAnalysisRepository
from music_analyzer.infrastructure.persistence.stage_mapping import stage_from_mapping


class StageBooleanValuesRedTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'analysis.sqlite'
        self.repository = SQLiteAnalysisRepository(str(self.path))
        self.identities = (FileIdentity('a' * 64, 123), FileIdentity('b' * 64, 123))
        self.locations = ('/music/song.flac', '/music/other.flac')
        self.repository.register(Inventory('/music', tuple(
            ScannedFile(location, identity, 1, 'flac',
                        TrackMetadata(duration_seconds=180.0, duration_source='mutagen'))
            for location, identity in zip(self.locations, self.identities)
        ), (), True))
        self.assertEqual(tuple(self.repository.track_ids()),
                         tuple(sorted(identity.track_id for identity in self.identities)))

        identity, other = self.identities
        self.other_run = self.repository.start(AudioSource(self.locations[1], other.track_id))
        for stage in (StageResult('bpm', (), '', (('bpm', 124.0),)),
                      StageResult('key', (), '', (('key', '8A'),)),
                      StageResult('genres', (), ''), StageResult('mood', (), ''),
                      StageResult('energy', (), '')):
            self.repository.save_stage(self.other_run, stage)
        self.repository.finish(self.other_run, 'completed', '')
        self.run_id = self.repository.start(AudioSource(self.locations[0], identity.track_id))
        self.existing_stage = StageResult('instruments', (), 'existing checkpoint',
                                          (('instrument', 'piano'),))
        self.repository.save_stage(self.run_id, self.existing_stage)
        edges = (ProjectionEdge(identity.track_id, other.track_id, 0.25, 2),)
        self.build_id = self.repository.replace_graph_snapshot(
            edges, 10, 'source-fp', positioned_edges=edges)

    def _publication_state(self):
        # Capture full small rows AFTER start and warming: start's intentional
        # invalidation is not the effect under test. Retained payloads, complete
        # run rows, current edges and both kinds of historical edges are covered.
        tables = ('runs', 'run_tracks', 'stages', 'graph_feature_evidence',
                  'graph_builds', 'graph_edges', 'graph_positioned_edges',
                  'graph_build_edges', 'graph_build_positioned_edges',
                  'graph_build_positioned_snapshots')
        with closing(sqlite3.connect(self.path)) as db:
            return tuple((table, tuple(db.execute(f'SELECT * FROM {table} ORDER BY rowid')))
                         for table in tables)

    def _assert_warm_fixture(self):
        stored = self.repository.read_track(self.identities[0].track_id)
        self.assertEqual((stored.run.run_id, stored.run.status, stored.run.stages),
                         (self.run_id, 'running', (self.existing_stage,)))
        self.assertEqual(self.repository.current_graph_snapshot(
            10, self.repository.source_revision())['state'], 'ready')
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute(
                'SELECT run_id FROM graph_feature_evidence WHERE is_current=1').fetchall(),
                [(self.other_run,)])
            self.assertEqual(db.execute(
                'SELECT is_current FROM graph_builds WHERE id=?',
                (self.build_id,)).fetchone(), (1,))
            for table in ('graph_edges', 'graph_positioned_edges', 'graph_build_edges',
                          'graph_build_positioned_edges', 'graph_build_positioned_snapshots'):
                self.assertEqual(db.execute(f'SELECT count(*) FROM {table}').fetchone(), (1,))

    def _assert_rejected_and_same_stage_retry(self, retry_value):
        malformed = StageResult('bpm', (), '', (('score', True),))
        # Establish the independent reader contract, not an incidental failed
        # finish/setup: the constructible DTO is specifically an invalid value.
        with self.assertRaisesRegex(ValueError, r'Invalid values'):
            stage_from_mapping(asdict(malformed))
        self._assert_warm_fixture()
        before = self._publication_state()
        statements = []
        connect = sqlite3.connect

        def traced_connect(*args, **kwargs):
            db = connect(*args, **kwargs)
            db.set_trace_callback(statements.append)
            return db

        # Observe the actual SQLite boundary without replacing save_stage or
        # any transaction method. Rejection must precede even BEGIN, not merely
        # roll back changes after acquiring the writer transaction.
        with patch('music_analyzer.infrastructure.persistence.analysis.sqlite3.connect',
                   side_effect=traced_connect):
            with self.assertRaisesRegex(AnalysisError, r'(?i)(stage.*value|boolean|numeric)'):
                self.repository.save_stage(self.run_id, malformed)
        self.assertFalse(any(sql.lstrip().upper().startswith('BEGIN') for sql in statements),
                         'Invalid numeric value must be rejected before a transaction begins')
        self.assertEqual(self._publication_state(), before,
                         'Rejected save must preserve entire runs/stages/evidence, current graph, '
                         'full history and positioned history')
        self._assert_warm_fixture()
        valid = StageResult('bpm', (), 'same-run and same-stage retry', (('score', retry_value),))
        self.assertEqual(stage_from_mapping(asdict(valid)), valid)
        self.repository.save_stage(self.run_id, valid)
        stored = self.repository.read_track(self.identities[0].track_id)
        self.assertEqual((stored.run.run_id, stored.run.status, stored.run.stages),
                         (self.run_id, 'running', (valid, self.existing_stage)))
        self.repository.finish(self.run_id, 'completed', '')
        self.assertEqual(self.repository.read_track(self.identities[0].track_id).run.status,
                         'completed')

    def test_save_stage_rejects_boolean_before_transaction_and_numeric_one_retries(self):
        self._assert_rejected_and_same_stage_retry(1)

    def test_save_stage_rejects_boolean_before_transaction_and_string_retries(self):
        self._assert_rejected_and_same_stage_retry('estimated')

    def test_scanner_complete_boolean_preserves_incomplete_and_complete_scan_behavior(self):
        self.assertEqual(self.repository.register(Inventory('/music', (), (), False)), ())
        for identity, location in zip(self.identities, self.locations):
            self.assertEqual(self.repository.locations(identity.track_id), (location,))
        self.assertEqual(self.repository.register(Inventory('/music', (), (), True)),
                         tuple(sorted(self.locations)))
        for identity in self.identities:
            self.assertEqual(self.repository.locations(identity.track_id), ())

    def test_optional_estimates_and_legitimate_summary_boolean_remain_readable(self):
        self._assert_warm_fixture()
        stages = (
            StageResult('bpm', (), '', (('score', 1), ('bpm', 'fast'))),
            StageResult('key', (), '', (('key', '8A'), ('strength', 0.7))),
            StageResult('genres', (), ''),
            StageResult('mood', (), ''),
            StageResult('energy', (), ''),
            StageResult('custom-estimate', (), '', summary=ScoreSummary(
                ('synthetic',), (0.7,), (0.7,), (0.7,), 1.0, provisional=True)),
        )
        for stage in stages:
            with self.subTest(stage=stage.stage):
                self.assertEqual(stage_from_mapping(asdict(stage)), stage)
                self.repository.save_stage(self.run_id, stage)
                stored = self.repository.read_track(self.identities[0].track_id)
                self.assertIn(stage, stored.run.stages)
                self.assertEqual(stored.run.status, 'running')
        # These are readable retained checkpoints, not a claim that a string
        # BPM satisfies the separate compact graph-evidence publication policy.
        self.repository.finish(self.run_id, 'interrupted', 'checkpoint control')
        self.assertEqual(self.repository.read_track(self.identities[0].track_id).run.status,
                         'interrupted')
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute(
                'SELECT run_id FROM graph_feature_evidence WHERE is_current=1').fetchall(),
                [(self.other_run,)])
            # Valid graph-relevant writes intentionally demote current graph,
            # without damaging either retained historical edge projection.
            self.assertEqual(db.execute(
                'SELECT status,is_current FROM graph_builds WHERE id=?',
                (self.build_id,)).fetchone(), ('completed', 0))
            for table in ('graph_build_edges', 'graph_build_positioned_edges',
                          'graph_build_positioned_snapshots'):
                self.assertEqual(db.execute(f'SELECT count(*) FROM {table}').fetchone(), (1,))
