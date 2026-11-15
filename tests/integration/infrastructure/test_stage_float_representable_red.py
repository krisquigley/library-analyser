"""Issue #111: float-overflowing integers are rejected at the originating save."""
from contextlib import closing
from dataclasses import asdict
import json
import sqlite3
import unittest
from unittest.mock import patch

from music_analyzer.application.dto.analysis import AnalysisError, StageResult
from music_explorer.infrastructure.explorer_readonly import AnalysisError as StandaloneAnalysisError
from tests.integration.infrastructure.test_stage_raw_window_writer_contract_red import StageWriterContractFixture


class StageFloatRepresentableWriterTests(StageWriterContractFixture):
    def test_save_rejects_float_overflowing_integer_before_transaction_and_retries(self):
        # 4000 digits: serializable as JSON (<4300), so #96 does not cover it.
        malformed = StageResult('mood', (), '', raw_predictions=(((10 ** 4000,),),))
        before = self._public_state()
        before_bytes = self.path.read_bytes()
        with patch('sqlite3.connect', wraps=sqlite3.connect) as connect:
            with self.assertRaisesRegex(AnalysisError, r'^Invalid stage result: '):
                self.writer.save_stage(self.run_id, malformed)
            connect.assert_not_called()
        self.assertEqual(self.path.read_bytes(), before_bytes)
        self.assertEqual(self._public_state(), before)
        self._valid_same_run_stage_retry()

    def test_already_stored_overflowing_stage_is_a_bounded_read_error(self):
        # Simulates a stage written by a custom engine before #111 (external SQL).
        # A consumed value (bpm) that every reader decodes.
        stored = StageResult('bpm', (), '', (('bpm', 10 ** 4000),))
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('INSERT INTO stages(run_id,stage,result) VALUES(?,?,?)',
                       (self.run_id, 'bpm', json.dumps(asdict(stored))))
        track_id = self.identities[0].track_id
        reads = {
            'writer_read_track': (AnalysisError, lambda: self.writer.read_track(track_id)),
            'standalone_read_track': (StandaloneAnalysisError, lambda: self.reader.read_track(track_id)),
            'standalone_candidates': (StandaloneAnalysisError, self.reader.candidate_snapshot),
            'standalone_graph': (StandaloneAnalysisError, lambda: self.reader.mood_axis_graph_snapshot(sparse_k=10)),
        }
        for name, (error, read) in reads.items():
            with self.subTest(read=name), self.assertRaises(error):
                read()  # never a raw OverflowError


if __name__ == '__main__':
    unittest.main()
