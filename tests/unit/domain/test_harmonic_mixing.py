"""Issue #122: harmonic mixing rules for playlist transitions."""
import unittest

from music_explorer.domain.harmonic_mixing import (
    DEFAULT_MINIMUM_KEY_STRENGTH, HarmonicMixing, MusicalKey, camelot_code, keys_compatible, usable_key)


def key(name):
    tonic, scale = name.split()
    return MusicalKey.parse(tonic, scale)


class CamelotTests(unittest.TestCase):
    def test_keys_map_to_the_camelot_wheel(self):
        cases = [('C major', '8B'), ('A minor', '8A'), ('G major', '9B'), ('E minor', '9A'), ('F major', '7B'),
                 ('D minor', '7A'), ('B major', '1B'), ('Ab minor', '1A'), ('G# minor', '1A'), ('Db major', '3B'),
                 ('C# major', '3B'), ('F# minor', '11A'), ('Bb major', '6B')]
        for name, code in cases:
            with self.subTest(name):
                self.assertEqual(code, camelot_code(key(name)))

    def test_unknown_spellings_do_not_parse(self):
        for tonic, scale in [('H', 'major'), ('C', 'dorian'), ('', 'minor'), (None, None), ('C', None)]:
            with self.subTest((tonic, scale)):
                self.assertIsNone(MusicalKey.parse(tonic, scale))

    def test_scale_is_case_insensitive(self):
        self.assertEqual(key('C major'), MusicalKey.parse('C', 'Major'))


class CompatibilityTests(unittest.TestCase):
    def test_compatible_transitions(self):
        cases = [('C major', 'C major', 'same code'), ('C major', 'G major', '+1'), ('C major', 'F major', '-1'),
                 ('C major', 'A minor', 'relative'), ('A minor', 'C major', 'relative'),
                 ('A minor', 'E minor', '+1'), ('B major', 'Gb major', '12B wraps to 1B'),
                 ('C# major', 'Db major', 'enharmonic')]
        for a, b, why in cases:
            with self.subTest(why=why, a=a, b=b):
                self.assertTrue(keys_compatible(key(a), key(b)))

    def test_incompatible_transitions(self):
        cases = [('C major', 'D major', '+2'), ('C major', 'E minor', 'diagonal'), ('C major', 'C minor', 'parallel'),
                 ('A minor', 'G major', 'diagonal')]
        for a, b, why in cases:
            with self.subTest(why=why, a=a, b=b):
                self.assertFalse(keys_compatible(key(a), key(b)))


class UsableKeyTests(unittest.TestCase):
    def test_a_key_at_or_above_the_minimum_strength_is_usable(self):
        self.assertEqual(key('C major'), usable_key('C', 'major', 0.5, minimum_strength=0.5))

    def test_a_weak_key_is_unknown(self):
        self.assertIsNone(usable_key('C', 'major', 0.49, minimum_strength=0.5))

    def test_zero_strength_is_unknown_even_with_a_zero_minimum(self):
        self.assertIsNone(usable_key('C', 'major', 0.0, minimum_strength=0.0))

    def test_a_missing_or_non_numeric_strength_is_unknown(self):
        for strength in (None, 'high', float('nan'), True):
            with self.subTest(strength):
                self.assertIsNone(usable_key('C', 'major', strength, minimum_strength=0.0))

    def test_minimum_strength_must_be_between_0_and_1(self):
        for minimum in (-0.01, 1.01, float('nan'), None):
            with self.subTest(minimum):
                with self.assertRaisesRegex(ValueError, 'between 0.0 and 1.0'):
                    HarmonicMixing(minimum_key_strength=minimum)

    def test_default_minimum_strength(self):
        self.assertEqual(0.5, DEFAULT_MINIMUM_KEY_STRENGTH)
        self.assertEqual(0.5, HarmonicMixing().minimum_key_strength)


class TransitionTests(unittest.TestCase):
    def setUp(self):
        self.mixing = HarmonicMixing()

    def test_compatible_key_raises_and_incompatible_key_lowers_the_relation_score(self):
        self.assertAlmostEqual(0.85, self.mixing.transition_score(0.8, key('C major'), key('G major'), 120, 120))
        self.assertAlmostEqual(0.75, self.mixing.transition_score(0.8, key('C major'), key('D major'), 120, 120))

    def test_unknown_key_is_neutral(self):
        self.assertAlmostEqual(0.8, self.mixing.transition_score(0.8, None, key('D major'), 120, 120))
        self.assertAlmostEqual(0.8, self.mixing.transition_score(0.8, key('C major'), None, 120, 120))

    def test_bpm_step_beyond_6_percent_is_penalised(self):
        self.assertAlmostEqual(0.8, self.mixing.transition_score(0.8, None, None, 100, 106), msg='exactly 6% is smooth')
        self.assertAlmostEqual(0.75, self.mixing.transition_score(0.8, None, None, 100, 107))
        self.assertAlmostEqual(0.75, self.mixing.transition_score(0.8, None, None, 107, 100), msg='either direction')

    def test_half_and_double_time_are_not_assumed(self):
        self.assertAlmostEqual(0.75, self.mixing.transition_score(0.8, None, None, 70, 140))

    def test_penalties_add_up_but_a_transition_is_never_excluded(self):
        score = self.mixing.transition_score(0.8, key('C major'), key('D major'), 100, 130)
        self.assertAlmostEqual(0.7, score)


    def test_a_bpm_step_is_smooth_within_the_tolerance_and_unknown_without_two_tempos(self):
        # #138: what a preview shows for each transition.
        self.assertEqual([True, False, False, None, None],
                         [self.mixing.bpm_step_smooth(*bpms) for bpms in ((100, 106), (100, 107), (107, 100), (None, 120),
                                                                          (0, 120))])

if __name__ == '__main__':
    unittest.main()
