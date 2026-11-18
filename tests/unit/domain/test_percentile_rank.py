"""Levels as percentile mid-ranks, shared by the energy plan and the mood hold (#123)."""
import unittest

from music_explorer.domain.percentile_rank import percentile_ranks


class PercentileRankTests(unittest.TestCase):
    def test_levels_are_mid_ranks_between_0_and_1(self):
        self.assertEqual({'a': 0.0, 'b': 0.5, 'c': 1.0}, percentile_ranks({'a': -3.0, 'b': 2.0, 'c': 9.5}))

    def test_ties_share_a_level(self):
        self.assertEqual({'a': 0.0, 'b': 0.75, 'c': 0.75}, percentile_ranks({'a': 1.0, 'b': 4.0, 'c': 4.0}))

    def test_a_single_value_is_the_middle(self):
        self.assertEqual({'a': 0.5}, percentile_ranks({'a': 7.0}))

    def test_no_values(self):
        self.assertEqual({}, percentile_ranks({}))


if __name__ == '__main__':
    unittest.main()
