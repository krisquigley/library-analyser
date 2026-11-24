"""Issue #132: the BPM and key text a tag would hold, a manual override winning over the detected value."""
import unittest

from music_explorer.domain.track_tag_values import bpm_tag_value, key_tag_value


class BpmTagValueTests(unittest.TestCase):
    def test_a_detected_bpm_is_written_as_a_whole_number(self):
        for detected, text in [(124.0, '124'), (123.5, '124'), (87.49, '87'), (174.2, '174')]:
            with self.subTest(detected=detected):
                self.assertEqual(text, bpm_tag_value(detected, None))

    def test_a_manual_override_wins(self):
        self.assertEqual('128', bpm_tag_value(124.0, '128'))
        self.assertEqual('100', bpm_tag_value(124.0, ' 99.6 '))

    def test_an_unknown_or_unusable_bpm_writes_nothing(self):
        for detected, manual in [(None, None), (0.0, None), (-5.0, None), (float('nan'), None), (True, None),
                                 (124.0, 'fast'), (124.0, '0'), (124.0, 'inf')]:
            with self.subTest(detected=detected, manual=manual):
                self.assertIsNone(bpm_tag_value(detected, manual))


class KeyTagValueTests(unittest.TestCase):
    def test_a_detected_key_strong_enough_is_written_in_standard_notation(self):
        cases = [('A', 'minor', 'Am'), ('C', 'major', 'C'), ('C#', 'minor', 'C#m'), ('Db', 'major', 'Db'),
                 ('F#', 'major', 'F#'), ('A#', 'minor', 'Bbm'), ('D#', 'minor', 'Ebm'), ('G#', 'major', 'Ab')]
        for tonic, scale, text in cases:
            with self.subTest(tonic=tonic, scale=scale):
                self.assertEqual(text, key_tag_value(tonic, scale, 0.8, None, minimum_strength=0.5))

    def test_a_weak_or_unknown_detected_key_writes_nothing(self):
        self.assertIsNone(key_tag_value('A', 'minor', 0.3, None, minimum_strength=0.5))
        self.assertIsNone(key_tag_value('H', 'minor', 0.9, None, minimum_strength=0.5))
        self.assertIsNone(key_tag_value(None, None, None, None, minimum_strength=0.5))

    def test_a_manual_key_wins_whatever_the_detected_strength(self):
        for manual, text in [('C major', 'C'), ('a minor', 'Am'), ('F#m', 'F#m'), ('Bb', 'Bb')]:
            with self.subTest(manual=manual):
                self.assertEqual(text, key_tag_value('A', 'minor', 0.1, manual, minimum_strength=0.5))

    def test_a_manual_key_that_cannot_be_read_writes_nothing(self):
        self.assertIsNone(key_tag_value('A', 'minor', 0.9, '8A', minimum_strength=0.5))


if __name__ == '__main__':
    unittest.main()
