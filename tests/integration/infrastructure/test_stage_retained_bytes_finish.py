"""Finish must bound retained stages even when external SQL bypassed save_stage."""
from contextlib import closing
from dataclasses import asdict, replace
import json
import sqlite3
import unittest

from music_analyzer.application.dto.analysis import AnalysisError
from tests.integration.infrastructure import test_stage_retained_bytes_red as fixtures


class StoredStageFinishBytesTests(unittest.TestCase):
    def setUp(self):
        # Reuse the bounded two-track fixture without discovering its tests again.
        self.fixture = fixtures.StageRetainedBytesRedTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)

    def _insert_stored_stage(self, run_id, stage):
        payload = json.dumps(asdict(stage), allow_nan=False, ensure_ascii=False)
        with closing(sqlite3.connect(self.fixture.path)) as db:
            db.execute('INSERT INTO stages(run_id,stage,result) VALUES(?,?,?)',
                       (run_id, stage.stage, payload))
            db.commit()

    def test_finish_rejects_oversized_retained_stage_without_publication_mutation(self):
        run_id, _, _ = self.fixture._running_candidate_with_warm_graph()
        stage = fixtures._multibyte_stage_at_limit()
        stage = replace(stage, uncertainty=stage.uncertainty + 'x')
        self.assertEqual(fixtures._serialized_bytes(stage), fixtures.RETAINED_STAGE_BYTE_LIMIT + 1)
        self._insert_stored_stage(run_id, stage)
        del stage
        before = self.fixture._publication_state()
        with self.assertRaisesRegex(AnalysisError, r'(?i)(stage|size|bytes|16\s*mi?b)'):
            self.fixture.repository.finish(run_id, 'completed', '')
        self.assertEqual(self.fixture._publication_state(), before,
                         'Rejected finish must roll back run, evidence and graph publication')

    def test_finish_accepts_exact_retained_stage_limit(self):
        run_id, _, _ = self.fixture._running_candidate_with_warm_graph()
        stage = fixtures._multibyte_stage_at_limit()
        self._insert_stored_stage(run_id, stage)
        del stage
        self.fixture.repository.finish(run_id, 'completed', '')
        with closing(sqlite3.connect(self.fixture.path)) as db:
            self.assertEqual(db.execute('SELECT status FROM runs WHERE id=?', (run_id,)).fetchone(),
                             ('completed',))
            self.assertEqual(db.execute('SELECT length(CAST(result AS BLOB)) FROM stages WHERE run_id=?',
                                        (run_id,)).fetchone(), (fixtures.RETAINED_STAGE_BYTE_LIMIT,))
