"""How the playlist walk ranks a transition (#121-#123, #137)."""
from dataclasses import dataclass
import unittest

from music_explorer.domain.playlist_walk import by_relation_score
from music_explorer.domain.transition_ranking import transition_ranking


@dataclass(frozen=True)
class _Track:
    track_id: str
    key: object = None
    bpm: float = 120.0


class _Plan:
    def __init__(self):
        self.targets_worked_out = 0

    def target_after(self, walk):
        self.targets_worked_out += 1
        return 0.5

    def miss(self, track_id, target):
        return {'near': 0.0, 'far': -0.3}[track_id]


class _Hold:
    def adjustment(self, track_id):
        return 0.05


class TransitionRankingTests(unittest.TestCase):
    def test_with_nothing_to_adjust_the_relation_score_ranks(self):
        self.assertIs(by_relation_score, transition_ranking(None, None, None))

    def test_the_plan_and_the_hold_adjust_the_relation_score(self):
        rank = transition_ranking(None, _Plan(), _Hold())
        walk = (_Track('start'),)

        self.assertAlmostEqual(0.85, rank(walk, _Track('near'), 0.8, 0.5))
        self.assertAlmostEqual(0.55, rank(walk, _Track('far'), 0.8, 0.5))

    def test_the_plan_s_target_is_worked_out_once_for_each_walk(self):
        plan = _Plan()
        rank = transition_ranking(None, plan, None)
        first, second = (_Track('start'),), (_Track('start'), _Track('near'))
        for walk in (first, first, second, second):
            rank(walk, _Track('near'), 0.8, 0.5)

        self.assertEqual(2, plan.targets_worked_out)


if __name__ == '__main__':
    unittest.main()
