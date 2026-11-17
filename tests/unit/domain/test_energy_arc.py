"""Issue #123: energy arc and mood hold rules for playlist positions."""
import unittest

from music_explorer.domain.energy_arc import ARC_SHAPES, EnergyArc, MoodHold, arc_target, percentile_ranks


class PercentileRankTests(unittest.TestCase):
    def test_levels_are_mid_ranks_between_0_and_1(self):
        self.assertEqual({'a': 0.0, 'b': 0.5, 'c': 1.0}, percentile_ranks({'a': -3.0, 'b': 2.0, 'c': 9.5}))

    def test_ties_share_a_level(self):
        self.assertEqual({'a': 0.0, 'b': 0.75, 'c': 0.75}, percentile_ranks({'a': 1.0, 'b': 4.0, 'c': 4.0}))

    def test_a_single_value_is_the_middle(self):
        self.assertEqual({'a': 0.5}, percentile_ranks({'a': 7.0}))

    def test_no_values(self):
        self.assertEqual({}, percentile_ranks({}))


class ArcTargetTests(unittest.TestCase):
    def test_shapes(self):
        self.assertEqual(('steady', 'rise', 'fall', 'peak'), ARC_SHAPES)

    def test_targets_through_the_playlist(self):
        cases = [
            ('steady', 0.4, [(0.0, 0.4), (0.5, 0.4), (1.0, 0.4)]),
            ('rise', 0.3, [(0.0, 0.3), (0.5, 0.6), (1.0, 0.9)]),
            ('rise', 0.95, [(0.0, 0.95), (1.0, 0.95)]),
            ('fall', 0.7, [(0.0, 0.7), (0.5, 0.4), (1.0, 0.1)]),
            ('fall', 0.05, [(1.0, 0.05)]),
            ('peak', 0.3, [(0.0, 0.3), (1 / 3, 0.6), (2 / 3, 0.9), (1.0, 0.3)]),
        ]
        for shape, start, points in cases:
            for position, target in points:
                with self.subTest(shape=shape, start=start, position=position):
                    self.assertAlmostEqual(target, arc_target(shape, start, position))

    def test_unknown_shape_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'steady, rise, fall or peak'):
            arc_target('wave', 0.5, 0.5)


class EnergyArcTests(unittest.TestCase):
    def test_a_track_on_the_target_is_not_penalised_and_a_miss_is(self):
        arc = EnergyArc('steady', {'start': 0.5, 'on': 0.5, 'off': 0.9}, start_track_id='start')

        self.assertAlmostEqual(0.0, arc.adjustment('on', 0.5))
        self.assertAlmostEqual(-0.24, arc.adjustment('off', 0.5))

    def test_unknown_energy_costs_a_quarter_range_miss(self):
        arc = EnergyArc('steady', {'start': 0.5}, start_track_id='start')

        self.assertAlmostEqual(-0.15, arc.adjustment('unknown', 0.5))

    def test_the_target_follows_the_position(self):
        arc = EnergyArc('rise', {'start': 0.1, 'late': 0.9}, start_track_id='start')

        self.assertLess(arc.adjustment('late', 0.0), arc.adjustment('late', 1.0))

    def test_a_start_without_known_energy_anchors_the_middle(self):
        arc = EnergyArc('steady', {'mid': 0.5}, start_track_id='start')

        self.assertAlmostEqual(0.0, arc.adjustment('mid', 0.0))

    def test_unknown_shape_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'steady, rise, fall or peak'):
            EnergyArc('wave', {}, start_track_id='start')


class MoodHoldTests(unittest.TestCase):
    def test_a_stronger_mood_scores_higher(self):
        hold = MoodHold({'calm': 1.0, 'busy': 0.0, 'middle': 0.5})

        self.assertAlmostEqual(0.05, hold.adjustment('calm'))
        self.assertAlmostEqual(-0.05, hold.adjustment('busy'))
        self.assertAlmostEqual(0.0, hold.adjustment('middle'))

    def test_unknown_mood_is_neutral(self):
        self.assertEqual(0.0, MoodHold({}).adjustment('unknown'))


if __name__ == '__main__':
    unittest.main()
