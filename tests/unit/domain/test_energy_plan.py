"""Issues #123 and #135: an energy plan sets a target energy level per playlist position."""
from dataclasses import dataclass
import unittest

from music_explorer.domain.energy_plan import (
    ARC_SHAPES, BY_DURATION, BY_TRACK_COUNT, ArcSegment, EnergyPlan, EnergyRange, arc_target)


class ArcTargetTests(unittest.TestCase):
    def test_shapes(self):
        self.assertEqual(('steady', 'rise', 'fall', 'peak', 'dip'), ARC_SHAPES)

    def test_targets_through_the_playlist(self):
        cases = [
            ('steady', 0.4, [(0.0, 0.4), (0.5, 0.4), (1.0, 0.4)]),
            ('rise', 0.3, [(0.0, 0.3), (0.5, 0.6), (1.0, 0.9)]),
            ('rise', 0.95, [(0.0, 0.95), (1.0, 0.95)]),
            ('fall', 0.7, [(0.0, 0.7), (0.5, 0.4), (1.0, 0.1)]),
            ('fall', 0.05, [(1.0, 0.05)]),
            ('peak', 0.3, [(0.0, 0.3), (1 / 3, 0.6), (2 / 3, 0.9), (1.0, 0.3)]),
            ('dip', 0.7, [(0.0, 0.7), (1 / 3, 0.4), (2 / 3, 0.1), (5 / 6, 0.4), (1.0, 0.7)]),
            ('dip', 0.05, [(2 / 3, 0.05), (1.0, 0.05)]),
        ]
        for shape, start, points in cases:
            for position, target in points:
                with self.subTest(shape=shape, start=start, position=position):
                    self.assertAlmostEqual(target, arc_target(shape, start, position))

    def test_unknown_shape_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'steady, rise, fall, peak or dip'):
            arc_target('wave', 0.5, 0.5)


class EnergyRangeTargetTests(unittest.TestCase):
    # #136: the listener sets how low and how high an arc goes, on the 0-1 rank scale.
    def test_targets_within_a_range(self):
        range_ = EnergyRange(low=0.3, high=0.7)
        cases = [
            ('rise', 0.4, [(0.0, 0.4), (0.5, 0.55), (1.0, 0.7)]),
            ('fall', 0.6, [(0.0, 0.6), (0.5, 0.45), (1.0, 0.3)]),
            ('peak', 0.4, [(0.0, 0.4), (2 / 3, 0.7), (1.0, 0.4)]),
            ('dip', 0.6, [(0.0, 0.6), (2 / 3, 0.3), (1.0, 0.6)]),
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
        self.assertAlmostEqual(0.8, arc_target('peak', 0.8, 2 / 3, range_))
        self.assertAlmostEqual(0.2, arc_target('dip', 0.2, 2 / 3, range_))

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
    duration_seconds: float | None = None


def _walk(*track_ids):
    return tuple(_Placed(track_id) for track_id in track_ids)


def _timed(*tracks):
    return tuple(_Placed(track_id, seconds) for track_id, seconds in tracks)


def _plan(shape, levels, length=10):
    return EnergyPlan((ArcSegment(shape, length),), levels, BY_TRACK_COUNT)


class EnergyPlanMissTests(unittest.TestCase):
    def test_a_track_on_the_target_is_not_penalised_and_a_miss_is(self):
        plan = _plan('steady', {'on': 0.5, 'off': 0.9})

        self.assertAlmostEqual(0.0, plan.miss('on', 0.5))
        self.assertAlmostEqual(-0.24, plan.miss('off', 0.5))

    def test_unknown_energy_costs_a_quarter_range_miss(self):
        self.assertAlmostEqual(-0.15, _plan('steady', {}).miss('unknown', 0.5))


class SingleArcPlanTests(unittest.TestCase):
    def test_the_target_follows_the_next_track_through_the_arc(self):
        plan = _plan('rise', {'start': 0.3}, length=3)

        self.assertAlmostEqual(0.6, plan.target_after(_walk('start')))
        self.assertAlmostEqual(0.9, plan.target_after(_walk('start', 'a')))
        self.assertAlmostEqual(0.9, plan.target_after(_walk('start', 'a', 'b')), msg='past the end holds the end')

    def test_the_arc_is_anchored_on_the_first_track_of_the_walk(self):
        plan = _plan('steady', {'low': 0.2, 'high': 0.8})

        self.assertAlmostEqual(0.2, plan.target_after(_walk('low', 'x')))
        self.assertAlmostEqual(0.8, plan.target_after(_walk('high', 'x')))

    def test_a_start_without_known_energy_anchors_the_middle(self):
        self.assertAlmostEqual(0.5, _plan('steady', {}).target_after(_walk('start')))

    def test_a_one_track_arc_is_already_at_its_end(self):
        self.assertAlmostEqual(0.9, _plan('rise', {'start': 0.3}, length=1).target_after(_walk('start')))

    def test_the_arc_follows_its_energy_range(self):
        plan = EnergyPlan((ArcSegment('rise', 2, EnergyRange(0.2, 0.6)),), {'start': 0.2}, BY_TRACK_COUNT)

        self.assertAlmostEqual(0.6, plan.target_after(_walk('start')))

    def test_by_duration_the_target_follows_the_time_the_next_track_starts(self):
        plan = EnergyPlan((ArcSegment('rise', 600),), {'start': 0.3}, BY_DURATION)

        self.assertAlmostEqual(0.6, plan.target_after(_timed(('start', 300))))
        self.assertAlmostEqual(0.9, plan.target_after(_timed(('start', 300), ('a', 400))))


def _chain(*arcs, timeline=BY_TRACK_COUNT, levels):
    return EnergyPlan(tuple(ArcSegment(shape, length) for shape, length in arcs), levels, timeline)


class ChainedArcTests(unittest.TestCase):
    def test_each_track_is_in_the_arc_its_place_falls_in(self):
        plan = _chain(('rise', 3), ('fall', 3), levels={'start': 0.3, 'b': 0.85})

        self.assertAlmostEqual(0.9, plan.target_after(_walk('start', 'a')), msg='the last track of the first arc')
        self.assertAlmostEqual(0.6, plan.target_after(_walk('start', 'a', 'b')), msg='a third of the way down')
        self.assertAlmostEqual(0.1, plan.target_after(_walk('start', 'a', 'b', 'c', 'd')), msg='the last track')
        self.assertAlmostEqual(0.1, plan.target_after(_walk('start', 'a', 'b', 'c', 'd', 'e')), msg='past the end')

    def test_an_arc_starts_from_the_level_the_previous_arc_actually_reached(self):
        for reached, target in ((0.85, 0.6), (0.7, 0.5), (0.1, 0.1)):
            with self.subTest(reached=reached):
                plan = _chain(('rise', 3), ('fall', 3), levels={'start': 0.3, 'b': reached})
                self.assertAlmostEqual(target, plan.target_after(_walk('start', 'a', 'b')))

    def test_unknown_energy_where_an_arc_ends_falls_back_to_that_arc_s_planned_end(self):
        plan = _chain(('rise', 3), ('fall', 3), levels={'start': 0.3})

        self.assertAlmostEqual(0.9 - 0.8 / 3, plan.target_after(_walk('start', 'a', 'b')))

    def test_the_fallback_carries_through_a_chain_of_unknown_levels(self):
        plan = _chain(('rise', 2), ('steady', 2), ('fall', 2), levels={'start': 0.3})

        self.assertAlmostEqual(0.9 - 0.8 / 2, plan.target_after(_walk('start', 'a', 'b', 'c')))

    def test_backtracking_to_another_track_moves_the_anchor_with_it(self):
        plan = _chain(('rise', 3), ('fall', 3), levels={'start': 0.3, 'b': 0.85, 'other': 0.7})
        reached = _walk('start', 'a', 'b')

        self.assertAlmostEqual(0.5, plan.target_after(_walk('start', 'a', 'other')))
        self.assertAlmostEqual(0.6, plan.target_after(reached))

    def test_by_duration_a_track_belongs_to_the_arc_it_starts_in(self):
        plan = _chain(('rise', 600), ('fall', 600), timeline=BY_DURATION, levels={'start': 0.3, 'a': 0.8})

        self.assertAlmostEqual(0.6, plan.target_after(_timed(('start', 300))), msg='starts in the first arc')
        self.assertAlmostEqual(0.8 - 0.7 / 6, plan.target_after(_timed(('start', 300), ('a', 400))),
                               msg='a started in the first arc and anchors the second')

    def test_later_tracks_in_an_arc_stay_anchored_where_the_arc_began(self):
        plan = _chain(('rise', 3), ('fall', 3), levels={'start': 0.3, 'b': 0.85, 'c': 0.5})

        self.assertAlmostEqual(0.85 - 0.75 * 2 / 3, plan.target_after(_walk('start', 'a', 'b', 'c')))

    def test_by_duration_a_track_starting_exactly_where_an_arc_begins_belongs_to_it(self):
        plan = _chain(('rise', 600), ('fall', 600), timeline=BY_DURATION, levels={'start': 0.3, 'a': 0.8})

        self.assertAlmostEqual(0.3 - 0.2 / 6, plan.target_after(_timed(('start', 600), ('a', 100))))

    def test_by_duration_an_arc_no_track_starts_in_is_passed_over_from_the_last_track_placed(self):
        plan = _chain(('rise', 100), ('steady', 100), ('fall', 600), timeline=BY_DURATION, levels={'start': 0.4})

        self.assertAlmostEqual(0.4 - 0.3 / 2, plan.target_after(_timed(('start', 500))))


class EnergyPlanShapeTests(unittest.TestCase):
    def test_a_plan_has_at_least_one_arc(self):
        with self.assertRaisesRegex(ValueError, 'at least one arc'):
            EnergyPlan((), {}, BY_TRACK_COUNT)

    def test_an_arc_lasts_a_positive_whole_number_of_tracks_or_a_positive_duration(self):
        for timeline, length in ((BY_TRACK_COUNT, 0), (BY_TRACK_COUNT, 2.5), (BY_TRACK_COUNT, True),
                                 (BY_DURATION, 0), (BY_DURATION, -60), (BY_DURATION, float('inf')), (BY_DURATION, None)):
            with self.subTest(timeline=timeline, length=length):
                with self.assertRaisesRegex(ValueError, 'length'):
                    EnergyPlan((ArcSegment('rise', length),), {}, timeline)

    def test_unknown_shape_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'steady, rise, fall, peak or dip'):
            ArcSegment('wave', 3)


if __name__ == '__main__':
    unittest.main()
