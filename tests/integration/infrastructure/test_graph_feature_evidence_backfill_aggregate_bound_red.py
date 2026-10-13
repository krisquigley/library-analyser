"""Bounded legacy backfill regressions: valid public stages, not invalid JSON.

Completed pre-cap rows are represented by replaying public save_stage output
into a healthy completed run. This keeps the fixture usable after finish gains
its own aggregate cap; SQL is only the explicit historical-file boundary.
"""
from contextlib import closing
from dataclasses import asdict, replace
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from music_analyzer.application.dto.analysis import AnalysisError, AudioSource
from music_analyzer.application.use_cases.graph_feature_evidence import (
    build_graph_feature_evidence, validate_graph_feature_evidence_payload,
)
from music_analyzer.domain.projection import ProjectionEdge
from tests.integration.infrastructure.test_graph_feature_evidence_aggregate_finish_red import _stages_at_evidence_size
from music_analyzer.infrastructure.persistence.analysis import SQLiteAnalysisRepository
from music_analyzer.infrastructure.persistence.explorer_readonly import ReadOnlyExplorerSQLiteRepository
from music_explorer.infrastructure.explorer_readonly import ReadOnlyExplorerSQLiteRepository as StandaloneReadOnlyExplorerSQLiteRepository
from tests.support.graph_evidence_backfill_fixture import (
    complete_graph_relevant_run, graph_relevant_stages,
    register_track,
)


LIMIT = 16 * 1024 * 1024
SCRATCH_LIMIT = 512 * 1024 * 1024


class GraphFeatureEvidenceBackfillAggregateBoundRedTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='p3-backfill-')
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'analysis.sqlite'
        self.repository = SQLiteAnalysisRepository(str(self.path))
        self.addCleanup(self._check_scratch_budget)

    def _check_scratch_budget(self):
        self.assertLessEqual(sum(p.stat().st_size for p in Path(self.temp.name).rglob('*') if p.is_file()), SCRATCH_LIMIT)

    def _completed(self, suffix):
        identity = register_track(self.repository, suffix)
        run = complete_graph_relevant_run(self.repository, identity)
        return identity, run

    def _remove_evidence(self):
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('DELETE FROM graph_feature_evidence')

    def _evidence_links(self):
        with closing(sqlite3.connect(self.path)) as db:
            return tuple(db.execute('SELECT track_id,run_id,is_current FROM graph_feature_evidence ORDER BY track_id,run_id'))

    def _non_evidence_digest(self):
        # All logical state except evidence rows (the earlier good publication
        # is intentionally retained). Stream lines; never print stage bytes.
        digest = hashlib.sha256()
        with closing(sqlite3.connect(self.path)) as db:
            for line in db.iterdump():
                if line.startswith('INSERT INTO "graph_feature_evidence"'):
                    continue
                digest.update(line.encode('utf-8'))
                digest.update(b'\n')
        return digest.hexdigest()

    def _graph_rows(self):
        tables = ('graph_builds', 'graph_edges', 'graph_build_edges',
                  'graph_positioned_edges', 'graph_build_positioned_edges',
                  'graph_build_positioned_snapshots')
        with closing(sqlite3.connect(self.path)) as db:
            return tuple((table, tuple(db.execute(f'SELECT * FROM {table} ORDER BY rowid'))) for table in tables)

    def _trace_backfill(self, statements):
        # Observe actual executed SQLite statements, without replacing any
        # repository policy, stage mapper, evidence builder, or fetch result.
        connect = sqlite3.connect

        def traced_connect(*args, **kwargs):
            db = connect(*args, **kwargs)
            db.set_trace_callback(lambda sql: statements.append(sql) if sql.lstrip().upper().startswith('SELECT') else None)
            return db

        return patch('sqlite3.connect', side_effect=traced_connect)

    def test_oversized_legacy_aggregate_rejects_per_row_preserving_earlier_success_and_retry(self):
        candidates = sorted((self._completed('a'), self._completed('b')), key=lambda item: item[0].track_id)
        (good, good_run), (bad, bad_run) = candidates
        self.repository.replace_graph_snapshot(
            (ProjectionEdge(good.track_id, bad.track_id, 0.25, 2),),
            10, 'fixture-source-fingerprint',
            positioned_edges=(ProjectionEdge(good.track_id, bad.track_id, 0.50, 2),),
        )
        # Public checkpoint serialization is authoritative. Generate the
        # retained bytes using save_stage on a running public source first.
        source_path = Path(self.temp.name) / 'checkpoint-source.sqlite'
        source = SQLiteAnalysisRepository(str(source_path))
        source_identity = register_track(source, bad.sha256[0])
        source_run = source.start(AudioSource(f'/music/{bad.sha256[0]}.flac', source_identity.track_id))
        uncertainty = 'é' * (7 * 256 * 1024)  # 3.5 MiB UTF8 each.
        oversized_stages = tuple(replace(stage, uncertainty=uncertainty) for stage in graph_relevant_stages())
        evidence = build_graph_feature_evidence(bad.track_id, bad_run, oversized_stages)
        validate_graph_feature_evidence_payload(bad.track_id, bad_run, evidence.fingerprint, evidence.payload)
        compact_size = len(evidence.payload_json().encode('utf-8'))
        self.assertGreater(compact_size, LIMIT)
        del evidence
        for stage in oversized_stages:
            source.save_stage(source_run, stage)
        with closing(sqlite3.connect(source_path)) as source_db, closing(sqlite3.connect(self.path)) as db, db:
            sizes = tuple(source_db.execute('SELECT length(CAST(result AS BLOB)) FROM stages WHERE run_id=? ORDER BY stage', (source_run,)))
            self.assertEqual(len(sizes), 5)
            self.assertTrue(all(size[0] < LIMIT for size in sizes))
            self.assertGreater(sum(size[0] for size in sizes), LIMIT)
            for stage_name, payload in source_db.execute('SELECT stage,result FROM stages WHERE run_id=? ORDER BY stage', (source_run,)):
                db.execute('UPDATE stages SET result=? WHERE run_id=? AND stage=?', (payload, bad_run, stage_name))
        self._remove_evidence()
        graph_before = self._graph_rows()
        non_evidence_before = self._non_evidence_digest()

        try:
            self.repository.backfill_graph_feature_evidence(limit=2)
        except AnalysisError as error:
            self.assertRegex(str(error), '(?i)(oversized|16 MiB)')
        else:
            # Demonstrate the unsupported publication, not an incidental
            # fixture error: both earlier good and oversized row committed.
            self.assertEqual(self._evidence_links(), tuple(sorted(((good.track_id, good_run, 1), (bad.track_id, bad_run, 1)))))
            with closing(sqlite3.connect(self.path)) as db:
                actual = db.execute('SELECT length(CAST(evidence_json AS BLOB)) FROM graph_feature_evidence WHERE run_id=?', (bad_run,)).fetchone()[0]
            self.assertEqual(actual, compact_size)
            self.fail(f'AnalysisError not raised: backfill committed aggregate evidence bytes={actual}; limit={LIMIT}; earlier good row retained')

        self.assertEqual(self._evidence_links(), ((good.track_id, good_run, 1),))
        self.assertEqual(self._graph_rows(), graph_before)
        self.assertEqual(self._non_evidence_digest(), non_evidence_before)
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute('SELECT status FROM runs WHERE id=?', (bad_run,)).fetchone(), ('completed',))
            self.assertEqual(tuple(db.execute('SELECT length(CAST(result AS BLOB)) FROM stages WHERE run_id=? ORDER BY stage', (bad_run,))), sizes)
        # Correct only the historical oversized row and resume: earlier good
        # evidence stays current, and exactly the bad row is repaired.
        with closing(sqlite3.connect(self.path)) as db, db:
            for stage in graph_relevant_stages():
                db.execute('UPDATE stages SET result=? WHERE run_id=? AND stage=?', (json.dumps(asdict(stage), ensure_ascii=False, allow_nan=False), bad_run, stage.stage))
        stats = self.repository.backfill_graph_feature_evidence(limit=2)
        self.assertEqual(stats['backfilled'], 1)
        self.assertEqual(self._evidence_links(), tuple(sorted(((good.track_id, good_run, 1), (bad.track_id, bad_run, 1)))))

    def test_oversized_existing_current_preflights_before_payload_fetch_or_healthy_stage_repair(self):
        identity, run = self._completed('a')
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('UPDATE graph_feature_evidence SET evidence_json=? WHERE run_id=?', ('x' * (LIMIT + 1), run))
            before = db.execute('SELECT fingerprint,length(CAST(evidence_json AS BLOB)),is_current FROM graph_feature_evidence WHERE run_id=?', (run,)).fetchone()
        statements = []
        rejection = None
        with self._trace_backfill(statements):
            try:
                self.repository.backfill_graph_feature_evidence()
            except AnalysisError as error:
                rejection = error
        with self.subTest(contract='reject before repair'):
            self.assertIsInstance(rejection, AnalysisError)
            self.assertRegex(str(rejection), '(?i)(oversized|16 MiB)')
        payload_fetches = [sql for sql in statements if sql.lstrip().upper().startswith('SELECT') and 'evidence_json' in sql.lower() and 'length(' not in sql.lower()]
        with self.subTest(contract='no oversized payload fetch'):
            self.assertEqual(payload_fetches, [], 'Oversized current evidence must not be selected into Python')
        with self.subTest(contract='no repair mutation'), closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute('SELECT fingerprint,length(CAST(evidence_json AS BLOB)),is_current FROM graph_feature_evidence WHERE run_id=?', (run,)).fetchone(), before)

    def test_exact_and_one_under_limit_multibyte_backfill_remain_supported(self):
        for target in (LIMIT - 1, LIMIT):
            with self.subTest(evidence_bytes=target), tempfile.TemporaryDirectory(dir=self.temp.name) as directory:
                path = Path(directory) / 'boundary.sqlite'
                repository = SQLiteAnalysisRepository(str(path))
                identity = register_track(repository, 'a')
                run = repository.start(AudioSource('/music/a.flac', identity.track_id))
                stages = _stages_at_evidence_size(identity.track_id, run, target)
                evidence = build_graph_feature_evidence(identity.track_id, run, stages)
                validate_graph_feature_evidence_payload(identity.track_id, run, evidence.fingerprint, evidence.payload)
                self.assertEqual(len(evidence.payload_json().encode('utf-8')), target)
                for stage in stages:
                    repository.save_stage(run, stage)
                repository.finish(run, 'completed', '')
                with closing(sqlite3.connect(path)) as db, db:
                    db.execute('DELETE FROM graph_feature_evidence')
                stats = repository.backfill_graph_feature_evidence()
                self.assertEqual(stats['backfilled'], 1)
                with closing(sqlite3.connect(path)) as db:
                    self.assertEqual(db.execute('SELECT length(CAST(evidence_json AS BLOB)),fingerprint,is_current FROM graph_feature_evidence WHERE run_id=?', (run,)).fetchone(), (target, evidence.fingerprint, 1))
                self.assertEqual(repository.backfill_graph_feature_evidence()['already_current'], 1)
                self.assertEqual(ReadOnlyExplorerSQLiteRepository(str(path)).track_ids(), (identity.track_id,))
                self.assertEqual(StandaloneReadOnlyExplorerSQLiteRepository(str(path)).track_ids(), (identity.track_id,))
                self._check_scratch_budget()

    def test_existing_stage_size_preflight_still_rejects_before_fetch(self):
        _identity, run = self._completed('a')
        self._remove_evidence()
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('UPDATE stages SET result=? WHERE run_id=? AND stage=?', ('x' * (LIMIT + 1), run, 'bpm'))
        statements = []
        with self._trace_backfill(statements):
            with self.assertRaisesRegex(AnalysisError, 'Oversized stored stage'):
                self.repository.backfill_graph_feature_evidence()
        self.assertFalse(any(sql.lstrip().upper().startswith('SELECT RESULT FROM STAGES') for sql in statements))
        self.assertEqual(self._evidence_links(), ())
