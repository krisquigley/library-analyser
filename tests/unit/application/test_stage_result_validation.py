import unittest

from music_analyzer.application.dto.analysis import StageResult
from music_analyzer.domain.analysis import ScoreSummary


class StageResultValidationTests(unittest.TestCase):
    def validate(self, result):
        from music_analyzer.application.use_cases.stage_result_validation import validate_stage_result
        validate_stage_result(result)

    def test_rejects_summary_vectors_that_do_not_match_labels(self):
        for field in ('mean', 'minimum', 'maximum'):
            values = dict(labels=('happy', 'dark'), mean=(0.7, 0.2),
                          minimum=(0.6, 0.1), maximum=(0.8, 0.3), coverage=1.0)
            values[field] = (0.7,)
            with self.subTest(field=field):
                with self.assertRaisesRegex(ValueError, 'stage summary'):
                    self.validate(StageResult('mood', (), '', summary=ScoreSummary(**values)))

    def test_rejects_summary_values_not_supported_by_retained_mapping(self):
        for summary in (
            ScoreSummary((), (), (), (), 1.0),
            ScoreSummary((3,), (0.7,), (0.6,), (0.8,), 1.0),
            ScoreSummary(('happy',), (True,), (0.6,), (0.8,), 1.0),
            ScoreSummary(('happy',), (float('inf'),), (0.6,), (0.8,), 1.0),
            ScoreSummary(('happy',), (0.7,), (0.6,), (0.8,), 0.0),
            ScoreSummary(('happy',), (0.7,), (0.6,), (0.8,), 1.1),
        ):
            with self.subTest(summary=summary):
                with self.assertRaisesRegex(ValueError, 'stage summary'):
                    self.validate(StageResult('mood', (), '', summary=summary))

    def test_accepts_valid_summary(self):
        self.validate(StageResult('mood', (), '', summary=ScoreSummary(
            ('happy', 'dark'), (0.7, 0.2), (0.6, 0.1), (0.8, 0.3), 0.5)))

    def test_preserves_string_checkpoint_values_and_optional_empty_outputs(self):
        for stage in (
            StageResult('bpm', (), '', (('bpm', 'fast'),)),
            StageResult('key', (), '', (('key', '8A'), ('strength', 0.7))),
            StageResult('genres', (), '', (('genre', 'house'),)),
            StageResult('genres', (), ''),
            StageResult('mood', (), ''),
            StageResult('energy', (), ''),
        ):
            with self.subTest(stage=stage.stage):
                self.validate(stage)
