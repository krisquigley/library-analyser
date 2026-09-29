import unittest

from music_analyzer.domain.library_duration_policy import (
    ACTIVE_LIBRARY_MAX_DURATION_SECONDS,
    DurationVerification,
    active_library_duration_policy,
)


class ActiveLibraryDurationPolicyTests(unittest.TestCase):
    def test_exact_threshold_is_active(self):
        decision = active_library_duration_policy(DurationVerification(1200.0, 'mutagen'))
        self.assertTrue(decision.active)
        self.assertEqual(decision.warning, None)

    def test_strictly_above_threshold_is_excluded_with_actionable_warning(self):
        decision = active_library_duration_policy(DurationVerification(1200.000001, 'ffprobe'))
        self.assertFalse(decision.active)
        self.assertIn(f'>{ACTIVE_LIBRARY_MAX_DURATION_SECONDS:.1f}s', decision.warning)
        self.assertIn('excluded from active library', decision.warning)
        self.assertIn('rescan', decision.warning.lower())

    def test_unknown_or_unreadable_duration_fails_closed_until_verified(self):
        for verification in (None, DurationVerification(None, 'mutagen'), DurationVerification(30.0, '')):
            decision = active_library_duration_policy(verification)
            self.assertFalse(decision.active)
            self.assertIn('duration unverified', decision.warning)
            self.assertIn('mutagen/ffprobe', decision.warning)

    def test_invalid_numeric_duration_fails_closed_even_from_trusted_source(self):
        for verification in (DurationVerification(0.0, 'mutagen'), DurationVerification(float('nan'), 'ffprobe')):
            decision = active_library_duration_policy(verification)
            self.assertFalse(decision.active)
            self.assertIn('duration invalid', decision.warning)

    def test_textual_tag_duration_is_not_accepted_as_verification(self):
        decision = active_library_duration_policy(DurationVerification(30.0, 'textual-tag'))
        self.assertFalse(decision.active)
        self.assertIn('duration unverified', decision.warning)


if __name__ == '__main__':
    unittest.main()
