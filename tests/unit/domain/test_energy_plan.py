"""Issues #123 and #135: an energy plan sets a target energy level per playlist position."""
from dataclasses import dataclass
import unittest

from music_explorer.domain.energy_plan import ARC_SHAPES, ArcSegment, EnergyPlan, EnergyRange, arc_target


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


class EnergyRangeTargetTests(unittest.TestCase):
    # #136: the listener sets how low and how high an arc goes, on the 0-1 rank scale.
    def test_targets_within_a_range(self):
        range_ = EnergyRange(low=0.3, high=0.7)
        cases = [
            ('rise', 0.4, [(0.0, 0.4), (0.5, 0.55), (1.0, 0.7)]),
            ('fall', 0.6, [(0.0, 0.6), (0.5, 0.45), (1.0, 0.3)]),
            ('peak', 0.4, [(0.0, 0.4), (2 / 3, 0.7), (1.0, 0.4)]),
            ('steady', 0.5, [(0.0, 0.5), (1.0, 0.5)]),
        ]
        for shape, start, points in cases:
            for position, target in points:
                with self.subTest(shape=shape, start=start, position=position):
                    self.assertAlmostEqual(target, arc_target(shape, start, position, range_))

    def test_steady_holds_the_start_level_clamped_into_the_range(self):
        range_ = EnergyRange(low=0.3, high=0.7)

        self.assertAlmostEqual(0.7, arc_target('steady', 0.95, 0.5, range_))
        self.assertAlmostEqual(0.3, arc_target('steady', 0.05, 0.5, range_))

    def test_without_a_range_steady_holds_the_start_level_wherever_it_is(self):
        self.assertAlmostEqual(0.95, arc_target('steady', 0.95, 0.5))

    def test_an_arc_never_heads_the_wrong_way(self):
        range_ = EnergyRange(low=0.3, high=0.7)

        self.assertAlmostEqual(0.8, arc_target('rise', 0.8, 1.0, range_))
        self.assertAlmostEqual(0.2, arc_target('fall', 0.2, 1.0, range_))

    def test_a_range_with_only_one_end_set_keeps_the_default_other_end(self):
        self.assertEqual(EnergyRange(0.1, 0.6), EnergyRange.of(low=None, high=0.6))
        self.assertEqual(EnergyRange(0.4, 0.9), EnergyRange.of(low=0.4, high=None))
        self.assertIsNone(EnergyRange.of(low=None, high=None))

    def test_a_range_must_lie_within_0_and_1_with_low_below_high(self):
        for low, high in ((-0.1, 0.5), (0.2, 1.1), (float('nan'), 0.5)):
            with self.subTest(low=low, high=high):
                with self.assertRaisesRegex(ValueError, 'Energy low and high must be between 0.0 and 1.0'):
                    EnergyRange(low, high)
        for low, high in ((0.5, 0.5), (0.7, 0.3)):
            with self.subTest(low=low, high=high):
                with self.assertRaisesRegex(ValueError, 'Energy low must be below energy high'):
                    EnergyRange(low, high)


@dataclass(frozen=True)
class _Placed:
    track_id: str


def _walk(*track_ids):
    return tuple(_Placed(track_id) for track_id in track_ids)


def _plan(shape, levels):
    return EnergyPlan((ArcSegment(shape),), levels)


class EnergyPlanTests(unittest.TestCase):
    def test_a_track_on_the_target_is_not_penalised_and_a_miss_is(self):
        plan = _plan('steady', {'start': 0.5, 'on': 0.5, 'off': 0.9})

        self.assertAlmostEqual(0.0, plan.adjustment(_walk('start'), 'on', 0.5))
        self.assertAlmostEqual(-0.24, plan.adjustment(_walk('start'), 'off', 0.5))

    def test_unknown_energy_costs_a_quarter_range_miss(self):
        plan = _plan('steady', {'start': 0.5})

        self.assertAlmostEqual(-0.15, plan.adjustment(_walk('start'), 'unknown', 0.5))

    def test_the_target_follows_the_position(self):
        plan = _plan('rise', {'start': 0.1, 'late': 0.9})

        self.assertLess(plan.adjustment(_walk('start'), 'late', 0.0), plan.adjustment(_walk('start'), 'late', 1.0))

    def test_the_arc_is_anchored_on_the_first_track_of_the_walk(self):
        plan = _plan('steady', {'low': 0.2, 'high': 0.8})

        self.assertAlmostEqual(0.0, plan.adjustment(_walk('low', 'x'), 'low', 0.5))
        self.assertAlmostEqual(0.0, plan.adjustment(_walk('high', 'x'), 'high', 0.5))

    def test_a_start_without_known_energy_anchors_the_middle(self):
        plan = _plan('steady', {'mid': 0.5})

        self.assertAlmostEqual(0.0, plan.adjustment(_walk('start'), 'mid', 0.0))

    def test_unknown_shape_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'steady, rise, fall or peak'):
            ArcSegment('wave')

    def test_the_arc_follows_its_energy_range(self):
        plan = EnergyPlan((ArcSegment('rise', EnergyRange(0.2, 0.6)),), {'start': 0.2, 'top': 0.6, 'peak': 0.9})

        self.assertAlmostEqual(0.0, plan.adjustment(_walk('start'), 'top', 1.0))
        self.assertAlmostEqual(-0.18, plan.adjustment(_walk('start'), 'peak', 1.0))

    def test_a_plan_has_one_arc_until_arcs_can_be_chained(self):
        for segments in ((), (ArcSegment('rise'), ArcSegment('fall'))):
            with self.subTest(count=len(segments)):
                with self.assertRaisesRegex(ValueError, 'one arc'):
                    EnergyPlan(segments, {})


if __name__ == '__main__':
    unittest.main()
