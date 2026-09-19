import unittest

from music_analyzer.domain.analysis import ScoreWindow, summarize_scores


class ScoreSummaryTests(unittest.TestCase):
    def test_equal_windows_preserve_mean_range_peak_and_coverage(self):
        result = summarize_scores(('piano', 'voice'), (
            ScoreWindow(0, 10, (0.2, 0.8)), ScoreWindow(20, 30, (0.8, 0.4))), 40)
        self.assertEqual(result.labels, ('piano', 'voice'))
        self.assertEqual(result.mean, (0.5, 0.6000000000000001))
        self.assertEqual(result.minimum, (0.2, 0.4))
        self.assertEqual(result.maximum, (0.8, 0.8))
        self.assertEqual(result.coverage, 0.5)
        self.assertTrue(result.provisional)
        self.assertIn('not calibrated', result.uncertainty)

    def test_duration_weighted_mean_and_no_threshold_labels(self):
        result = summarize_scores(('solo',), (
            ScoreWindow(0, 1, (1.0,)), ScoreWindow(1, 4, (0.0,))), 4)
        self.assertEqual(result.mean, (0.25,))
        self.assertEqual(result.maximum, (1.0,))
        self.assertEqual(result.coverage, 1)

    def test_rejects_empty_nonfinite_mismatched_overlapping_or_outside_windows(self):
        cases = [
            ((), (), 10),
            (('a',), (), 10),
            (('a', 'a'), (ScoreWindow(0, 1, (0.2, 0.3)),), 10),
            (('a',), (ScoreWindow(0, 1, (float('nan'),)),), 10),
            (('a',), (ScoreWindow(0, 1, (float('inf'),)),), 10),
            (('a',), (ScoreWindow(0, 1, (0.1, 0.2)),), 10),
            (('a',), (ScoreWindow(0, 2, (0.1,)), ScoreWindow(1, 3, (0.2,))), 10),
            (('a',), (ScoreWindow(-1, 1, (0.1,)),), 10),
            (('a',), (ScoreWindow(1, 1, (0.1,)),), 10),
            (('a',), (ScoreWindow(0, 11, (0.1,)),), 10),
            (('a',), (ScoreWindow(0, 1, (0.1,)),), float('inf')),
        ]
        for labels, windows, duration in cases:
            with self.subTest(labels=labels, windows=windows, duration=duration):
                with self.assertRaises(ValueError):
                    summarize_scores(labels, windows, duration)
