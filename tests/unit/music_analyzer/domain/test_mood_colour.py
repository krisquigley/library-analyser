"""Issue #134: a track's mood quadrant (arousal x valence levels, split at the median) as a Mixxx colour."""
import unittest

from music_analyzer.domain.mood_colour import (
    CALM, MOOD_QUADRANTS, SOMBRE, TENSE, UPBEAT, mood_quadrant)


class MoodQuadrantTests(unittest.TestCase):
    def test_each_quadrant_has_its_colour(self):
        cases = [(0.9, 0.9, UPBEAT, 0xF8D200), (0.1, 0.9, TENSE, 0xC50A08), (0.9, 0.1, CALM, 0x32BE44),
                 (0.1, 0.1, SOMBRE, 0x0044FF)]
        for valence, arousal, quadrant, rgb in cases:
            with self.subTest(quadrant=quadrant.name):
                self.assertIs(quadrant, mood_quadrant(valence, arousal))
                self.assertEqual(rgb, quadrant.rgb)

    def test_the_median_itself_has_no_quadrant(self):
        for valence, arousal in [(0.5, 0.5), (0.5, 0.9), (0.1, 0.5)]:
            with self.subTest(valence=valence, arousal=arousal):
                self.assertIsNone(mood_quadrant(valence, arousal))

    def test_just_either_side_of_the_median(self):
        self.assertIs(UPBEAT, mood_quadrant(0.5001, 0.5001))
        self.assertIs(SOMBRE, mood_quadrant(0.4999, 0.4999))

    def test_the_colours_are_distinct_24_bit_rgb(self):
        colours = [quadrant.rgb for quadrant in MOOD_QUADRANTS]
        self.assertEqual(4, len(set(colours)))
        self.assertTrue(all(0 <= colour <= 0xFFFFFF for colour in colours))


if __name__ == '__main__':
    unittest.main()
