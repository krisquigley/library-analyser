import unittest

from music_analyzer.application.dto.analysis import StageResult
from music_analyzer.domain.analysis import ScoreSummary, ScoreWindow, summarize_scores


class StageResultValidationTests(unittest.TestCase):
    def validate(self, result):
        from music_analyzer.application.use_cases.stage_result_validation import validate_stage_result
        validate_stage_result(result)

    def test_rejects_nontext_stage_and_uncertainty(self):
        for result in (StageResult(123, (), ''), StageResult('instruments', (), 123)):
            with self.subTest(result=result):
                with self.assertRaisesRegex(ValueError, 'stage text'):
                    self.validate(result)

    def test_rejects_provenance_that_is_not_text_pairs(self):
        for provenance in (None, 'source', (('source', 123),), ((123, 'synthetic'),),
                           (('source',),), (('source', 'synthetic', 'extra'),)):
            with self.subTest(provenance=provenance):
                with self.assertRaisesRegex(ValueError, 'stage provenance'):
                    self.validate(StageResult('instruments', provenance, ''))

    def test_accepts_text_provenance_and_open_stage_names(self):
        self.validate(StageResult('custom-stage', (('source', 'synthetic'),), 'uncertain',
                                  (('instrument', 'piano'), ('confidence', 0.75), ('count', 2))))

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

    def test_rejects_values_not_supported_by_retained_mapping(self):
        for values in (None, 'score', ((123, 1),), (('score',),),
                       (('score', 1, 2),), (('score', True),), (('score', False),),
                       (('score', float('nan')),), (('score', float('inf')),),
                       (('score', None),)):
            with self.subTest(values=values):
                with self.assertRaisesRegex(ValueError, 'stage values'):
                    self.validate(StageResult('bpm', (), '', values))

    def test_accepts_finite_numeric_and_string_values_with_optional_summary(self):
        for summary in (None, ScoreSummary(('score',), (0.7,), (0.6,), (0.8,), 1.0)):
            for values in ((), [], (('score', 1),), (('score', 0.5),),
                           (('score', -2),), (('score', 'estimated'),)):
                with self.subTest(summary=summary, values=values):
                    self.validate(StageResult('bpm', (), '', values, summary=summary))

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

    def test_rejects_raw_leaves_that_are_not_finite_numbers_without_summary(self):
        for score in ('not-a-score', True, None, float('nan'), float('inf')):
            with self.subTest(score=score):
                with self.assertRaisesRegex(ValueError, 'raw scores'):
                    self.validate(StageResult('energy', (), '', raw_predictions=(((score,),),)))

    def test_rejects_malformed_raw_nesting(self):
        for raw in (None, 'scores', (None,), ((None,),), (((0.7,), 0.2),)):
            with self.subTest(raw=raw):
                with self.assertRaisesRegex(ValueError, 'raw scores'):
                    self.validate(StageResult('energy', (), '', raw_predictions=raw))

    def test_rejects_windows_without_summary(self):
        with self.assertRaisesRegex(ValueError, 'Windows require summary'):
            self.validate(StageResult('mood', (), '', windows=(ScoreWindow(0, 1, (0.7,)),)))

    def test_rejects_invalid_window_coverage_and_scores(self):
        summary = ScoreSummary(('happy',), (0.7,), (0.7,), (0.7,), 1.0)
        for windows in (
            (ScoreWindow(-1, 1, (0.7,)),),
            (ScoreWindow(0, 1, (0.7,)), ScoreWindow(0.5, 1.5, (0.7,))),
            (ScoreWindow(0, 1, (0.7, 0.2)),),
            (ScoreWindow(0, 1, (True,)),),
            (ScoreWindow(0, 1, ('score',)),),
            (ScoreWindow(0, 1, (float('inf'),)),),
        ):
            with self.subTest(windows=windows):
                with self.assertRaisesRegex(ValueError, 'coverage window'):
                    self.validate(StageResult('mood', (), '', windows=windows, summary=summary))

    def test_validates_labels_strictly_only_when_windows_are_present(self):
        for labels in (('',), ('happy', 'happy')):
            summary = ScoreSummary(labels, (0.7,) * len(labels), (0.7,) * len(labels),
                                   (0.7,) * len(labels), 1.0)
            self.validate(StageResult('mood', (), '', summary=summary))
            with self.assertRaisesRegex(ValueError, 'Labels'):
                self.validate(StageResult('mood', (), '', summary=summary,
                                          windows=(ScoreWindow(0, 1, (0.7,) * len(labels)),)))

    def test_accepts_optional_raw_and_retained_summary_without_score_comparison(self):
        for raw in ((), ((),), (((),),), (((-2, 3.5),),)):
            with self.subTest(raw=raw):
                self.validate(StageResult('energy', (), '', raw_predictions=raw))
        self.validate(StageResult('mood', (), '', raw_predictions=(((0.2, 0.9),),),
                                  windows=(ScoreWindow(0, 1, (0.7,)),),
                                  summary=ScoreSummary(('happy',), (0.1,), (-5,), (9,), 1.0)))

    def test_accepts_reconstructed_duration_roundoff_but_not_material_inconsistency(self):
        duration = 324.16
        windows = (ScoreWindow(0, 30, (0.2,)), ScoreWindow(147.08, 177.08, (0.3,)),
                   ScoreWindow(294.16, duration, (0.4,)))
        summary = summarize_scores(('label',), windows, duration)
        self.assertLess(sum(w.end - w.start for w in windows) / summary.coverage, duration)
        self.validate(StageResult('mood', (), '', windows=windows, summary=summary))
        inconsistent = ScoreSummary(summary.labels, summary.mean, summary.minimum, summary.maximum, 0.5)
        with self.assertRaisesRegex(ValueError, 'coverage window'):
            self.validate(StageResult('mood', (), '', windows=windows, summary=inconsistent))

    def test_rejects_malformed_windows_and_boundaries_before_duration_arithmetic(self):
        summary = ScoreSummary(('happy',), (0.7,), (0.7,), (0.7,), 1.0)
        invalid = (None, 'windows', (None,), (0.7,),
                   (ScoreWindow(0, 1, None),), (ScoreWindow(0, 1, 0.7),))
        invalid += tuple((ScoreWindow(value, 1, (0.7,)),) for value in
                         ('start', None, True, float('inf')))
        invalid += tuple((ScoreWindow(0, value, (0.7,)),) for value in
                         ('end', None, True, float('inf')))
        for windows in invalid:
            with self.subTest(windows=windows):
                with self.assertRaisesRegex(ValueError, 'coverage window'):
                    self.validate(StageResult('mood', (), '', windows=windows, summary=summary))

    def test_normalizes_window_arithmetic_overflow_as_invalid_window(self):
        summary = ScoreSummary(('happy',), (0.7,), (0.7,), (0.7,), 1.0)
        with self.assertRaisesRegex(ValueError, 'Invalid .*window'):
            self.validate(StageResult('mood', (), '',
                                      windows=(ScoreWindow(0, 10**309, (0.7,)),),
                                      summary=summary))

    def test_accepts_float_and_integer_window_arithmetic(self):
        for end, coverage in ((10, 1), (10, 1.0), (10.0, 1.0)):
            with self.subTest(end=end, coverage=coverage):
                self.validate(StageResult('mood', (), '',
                                          windows=(ScoreWindow(0, end, (0.7,)),),
                                          summary=ScoreSummary(('happy',), (0.7,), (0.7,),
                                                               (0.7,), coverage)))

    def test_rejects_absent_windows_container_without_summary(self):
        with self.assertRaisesRegex(ValueError, 'coverage window'):
            self.validate(StageResult('mood', (), '', windows=None))
