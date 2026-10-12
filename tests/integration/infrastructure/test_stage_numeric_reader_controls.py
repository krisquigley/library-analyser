"""Small reader/pure-policy controls for boolean numeric stage readability.

These tests do not tighten the reader contract or introduce graph semantics.
The writer rejection regression lives separately at the public save boundary.
"""
from dataclasses import asdict, replace
import unittest

from music_analyzer.application.dto.analysis import StageResult
from music_analyzer.application.use_cases.stage_result_validation import validate_stage_result
from music_analyzer.domain.analysis import ScoreSummary, ScoreWindow, finite
from music_analyzer.infrastructure.persistence.stage_mapping import stage_from_mapping


class StageNumericReaderControlsTests(unittest.TestCase):
    def test_finite_excludes_both_booleans_and_nonfinite_numbers(self):
        for value in (True, False, float('nan'), float('inf'), -float('inf')):
            with self.subTest(value=value):
                self.assertFalse(finite(value))
        for value in (0, 1, -1, 0.75):
            with self.subTest(value=value):
                self.assertTrue(finite(value))

    def test_reader_rejects_boolean_values(self):
        for value in (True, False):
            with self.subTest(value=value):
                stage = StageResult('instruments', (), '', (('score', value),))
                with self.assertRaisesRegex(ValueError, 'Invalid values'):
                    stage_from_mapping(asdict(stage))

    def test_reader_rejects_boolean_raw_scores(self):
        for value in (True, False):
            with self.subTest(value=value):
                stage = StageResult('instruments', (), '', raw_predictions=(((value,),),))
                with self.assertRaisesRegex(ValueError, 'Invalid raw scores'):
                    stage_from_mapping(asdict(stage))

    def test_reader_rejects_boolean_window_bounds_and_scores(self):
        summary = ScoreSummary(('piano',), (0.75,), (0.75,), (0.75,), 1.0)
        for window in (ScoreWindow(False, 1.0, (0.75,)),
                       ScoreWindow(0.0, True, (0.75,)),
                       ScoreWindow(0.0, 1.0, (True,)),
                       ScoreWindow(0.0, 1.0, (False,))):
            with self.subTest(window=window):
                stage = StageResult('instruments', (), '', windows=(window,), summary=summary)
                with self.assertRaisesRegex(ValueError, 'coverage window'):
                    stage_from_mapping(asdict(stage))

    def test_reader_and_pure_policy_reject_boolean_summary_numbers(self):
        summary = ScoreSummary(('piano',), (0.75,), (0.75,), (0.75,), 1.0)
        for field in ('mean', 'minimum', 'maximum', 'coverage'):
            for value in (True, False):
                with self.subTest(field=field, value=value):
                    malformed = replace(summary, **{field: value if field == 'coverage' else (value,)})
                    stage = StageResult('instruments', (), '', summary=malformed)
                    with self.assertRaisesRegex(ValueError, 'Invalid summary'):
                        stage_from_mapping(asdict(stage))
                    with self.assertRaisesRegex(ValueError, 'Invalid stage summary'):
                        validate_stage_result(stage)

    def test_reader_and_pure_policy_accept_numeric_and_string_estimates(self):
        stage = StageResult('instruments', (('source', 'synthetic'),), 'provisional',
                            (('score', 0.75), ('count', 2), ('instrument', 'piano')))
        validate_stage_result(stage)
        self.assertEqual(stage_from_mapping(asdict(stage)), stage)

    def test_reader_and_pure_policy_accept_empty_and_summary_only_checkpoints(self):
        stages = (StageResult('genres', (), ''),
                  StageResult('mood', (), '', summary=ScoreSummary(
                      ('happy',), (0.75,), (0.75,), (0.75,), 1.0)))
        for stage in stages:
            with self.subTest(stage=stage.stage):
                validate_stage_result(stage)
                self.assertEqual(stage_from_mapping(asdict(stage)), stage)

    def test_reader_and_pure_policy_accept_numeric_windows_and_raw_scores(self):
        stage = StageResult('instruments', (), '', windows=(ScoreWindow(0.0, 1.0, (0.75,)),),
                            summary=ScoreSummary(('piano',), (0.75,), (0.75,), (0.75,), 1.0),
                            raw_predictions=(((0.75,),),))
        validate_stage_result(stage)
        self.assertEqual(stage_from_mapping(asdict(stage)), stage)
