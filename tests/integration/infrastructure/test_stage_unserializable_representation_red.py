"""Issue #96: unserializable stage values fail at the originating save.

A custom engine may return a Python integer beyond the JSON encoder's integer
string conversion limit. The public writer must reject it as a bounded
AnalysisError before any transaction, with no mutation or graph invalidation,
so AnalyzeTrack finalizes the run as failed instead of leaving it running.

Since #111 the domain numeric policy rejects such integers first (they are not
float-representable); the encoder boundary remains as defense in depth and is
exercised directly with an injected representation ValueError.
"""
from contextlib import contextmanager
import sqlite3
import unittest
from unittest.mock import patch

from music_analyzer.application.dto.analysis import AnalysisError, AudioSource, DecodedAudio, StageResult
from music_analyzer.application.use_cases.analyze_track import AnalyzeTrack
from music_analyzer.application.use_cases.stage_result_validation import validate_stage_result
from tests.integration.infrastructure.test_stage_raw_window_writer_contract_red import StageWriterContractFixture

GIANT = 10 ** 5000  # beyond the default 4300-digit str conversion limit


def unserializable_mood():
    return StageResult('mood', (), '', raw_predictions=(((GIANT,),),))


class StageUnserializableRepresentationTests(StageWriterContractFixture):
    def test_fixture_value_is_rejected_by_the_numeric_policy_since_issue111(self):
        with self.assertRaises(ValueError):
            validate_stage_result(unserializable_mood())

    def test_encoder_representation_error_is_normalized_before_transaction(self):
        before_bytes = self.path.read_bytes()
        with patch('music_analyzer.infrastructure.persistence.analysis.json.dumps',
                   side_effect=ValueError('Exceeds the limit (4300 digits) for integer string conversion')), \
                patch('sqlite3.connect', wraps=sqlite3.connect) as connect:
            with self.assertRaisesRegex(AnalysisError, r'^Invalid stage result: value is not serializable'):
                self.writer.save_stage(self.run_id, self._valid_scores())
            connect.assert_not_called()
        self.assertEqual(self.path.read_bytes(), before_bytes)
        self._valid_same_run_stage_retry()

    def test_save_rejects_unserializable_integer_before_transaction_and_same_stage_retries(self):
        before = self._public_state()
        before_bytes = self.path.read_bytes()
        with patch('sqlite3.connect', wraps=sqlite3.connect) as connect:
            with self.assertRaisesRegex(AnalysisError, r'^Invalid stage result: '):
                self.writer.save_stage(self.run_id, unserializable_mood())
            connect.assert_not_called()
        self.assertEqual(self.path.read_bytes(), before_bytes)
        self.assertEqual(self._public_state(), before)
        self.assertEqual(self.writer.current_graph_snapshot(10, self.revision)['build_id'], self.build_id)
        self._valid_same_run_stage_retry()

    def test_unexpected_encoder_failures_are_not_normalized(self):
        with patch('music_analyzer.infrastructure.persistence.analysis.json.dumps',
                   side_effect=TypeError('unexpected programmer error')):
            # Validated leaves are str/int/float, so only the encoder's
            # ValueError is a known representation failure; others propagate.
            with self.assertRaisesRegex(TypeError, 'unexpected programmer error'):
                self.writer.save_stage(self.run_id, self._valid_scores())

    def test_analyze_track_finalizes_failed_run_for_unserializable_stage(self):
        cleaned = []

        class Decoder:
            @contextmanager
            def decode(self, source, max_duration):
                try:
                    yield DecodedAudio('synthetic-handle', 10, 44100)
                finally:
                    cleaned.append(True)

        class Engine:
            def analyze(self, stage, audio):
                if stage == 'mood':
                    return unserializable_mood()
                return StageResult(stage, (), '')

        # The fixture's candidate run is still running; finish it so a new run starts.
        self.writer.finish(self.run_id, 'interrupted', 'superseded by test')
        source = AudioSource('/music/candidate.flac', self.identities[0].track_id)

        report = AnalyzeTrack(Decoder(), Engine(), self.writer).execute(source)

        self.assertEqual(cleaned, [True], 'decoded audio is released on the failure path')
        self.assertEqual(report.status, 'failed')
        self.assertRegex(report.detail, r'^mood: Invalid stage result: ')
        stored = self.writer.read_track(self.identities[0].track_id).run
        self.assertEqual((stored.run_id, stored.status), (report.run_id, 'failed'))
        self.assertEqual(tuple(stage.stage for stage in stored.stages), ('bpm', 'genres', 'key'))


if __name__ == '__main__':
    unittest.main()
