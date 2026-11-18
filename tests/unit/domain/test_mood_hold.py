"""Issue #123: a mood hold prefers tracks stronger in the chosen mood."""
import unittest

from music_explorer.domain.mood_hold import MoodHold


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
