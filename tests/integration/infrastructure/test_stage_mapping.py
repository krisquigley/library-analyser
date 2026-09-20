from dataclasses import asdict
import unittest

from music_analyzer.application.dto.analysis import StageResult
from music_analyzer.domain.analysis import ScoreWindow, summarize_scores
from music_analyzer.infrastructure.persistence.stage_mapping import stage_from_mapping


class StageMappingTests(unittest.TestCase):
    def result(self):
        duration = 324.16
        windows = (ScoreWindow(0, 30, (.2,)),
                   ScoreWindow(147.08, 177.08, (.3,)),
                   ScoreWindow(294.16, duration, (.4,)))
        return StageResult('mood', (), 'provisional', windows=windows,
                           summary=summarize_scores(('label',), windows, duration))

    def test_fractional_duration_round_trip_preserves_evidence(self):
        result = self.result()
        self.assertEqual(stage_from_mapping(asdict(result)), result)

    def test_materially_inconsistent_coverage_is_still_rejected(self):
        data = asdict(self.result())
        data['summary']['coverage'] = .5
        with self.assertRaisesRegex(ValueError, 'coverage window'):
            stage_from_mapping(data)
