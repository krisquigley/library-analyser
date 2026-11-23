"""Issue #134: the analyzer's levels as percentile mid-ranks among the tracks being exported."""
import unittest

from music_analyzer.domain.percentile_rank import MIDDLE_LEVEL, percentile_ranks


class PercentileRankTests(unittest.TestCase):
    def test_values_rank_from_zero_to_one(self):
        self.assertEqual({'a': 0.0, 'b': 0.5, 'c': 1.0}, percentile_ranks({'b': 0.2, 'a': -1.5, 'c': 3.0}))

    def test_ties_share_their_mid_rank(self):
        self.assertEqual({'a': 0.0, 'b': 0.5, 'c': 0.5, 'd': 1.0},
                         percentile_ranks({'a': 1.0, 'b': 2.0, 'c': 2.0, 'd': 3.0}))

    def test_one_track_is_in_the_middle_and_none_gives_nothing(self):
        self.assertEqual({'a': MIDDLE_LEVEL}, percentile_ranks({'a': 7.0}))
        self.assertEqual({}, percentile_ranks({}))


if __name__ == '__main__':
    unittest.main()
