import unittest
from music_analyzer.domain.analysis import ScoreWindow, select_scores

class ThresholdTests(unittest.TestCase):
    def test_threshold_changes_only_aggregate_retained_scores(self):
        windows = (ScoreWindow(0, 10, (.2, .8)),)
        self.assertEqual(select_scores(('a', 'b'), windows, 10, .5), ('b',))
        self.assertEqual(select_scores(('a', 'b'), windows, 10, .1), ('a', 'b'))
        with self.assertRaises(ValueError): select_scores(('a','b'), windows, 10, float('nan'))
