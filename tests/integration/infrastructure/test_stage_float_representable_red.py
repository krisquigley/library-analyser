"""Issue #111: float-overflowing integers are rejected at the originating save."""
import sqlite3
import unittest
from unittest.mock import patch

from music_analyzer.application.dto.analysis import AnalysisError, StageResult
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


if __name__ == '__main__':
    unittest.main()
