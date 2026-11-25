"""Issue #265: where the eligible tracks' arousal lies, in the graph's own numbers."""
import unittest

from music_explorer.domain.arousal_scale import ArousalScale


class ArousalScaleTests(unittest.TestCase):
    def test_the_defaults_are_the_10th_and_90th_percentiles_the_middle_the_median(self):
        self.assertEqual(ArousalScale(low=3.4, high=6.6, middle=5.0, span=4.0),
                         _rounded(ArousalScale.of([7.0, 3.0, 5.0, 4.0, 6.0])))

    def test_one_track_or_identical_values_have_no_spread_but_a_usable_span(self):
        self.assertEqual(ArousalScale(4.2, 4.2, 4.2, 1.0), ArousalScale.of([4.2]))
        self.assertEqual(ArousalScale(5.0, 5.0, 5.0, 1.0), ArousalScale.of([5.0, 5.0]))

    def test_with_no_known_arousal_the_scale_is_neutral(self):
        self.assertEqual(ArousalScale(0.0, 1.0, 0.5, 1.0), ArousalScale.of([]))


def _rounded(scale):
    return ArousalScale(*(round(value, 9) for value in (scale.low, scale.high, scale.middle, scale.span)))


if __name__ == '__main__':
    unittest.main()
