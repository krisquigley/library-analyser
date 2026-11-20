"""Which tracks a playlist may use (#58, #120)."""
from dataclasses import dataclass
import unittest

from music_explorer.domain.playlist_eligibility import BpmRange, check_start_track, eligible


@dataclass(frozen=True)
class _Track:
    bpm: object = 120
    path: str = '/library/a.flac'
    active: bool = True
    catalogued: bool = True
    exists: bool = True
    manual_overrides: tuple = ()


class BpmRangeTests(unittest.TestCase):
    def test_a_range_from_values_as_entered(self):
        self.assertEqual(BpmRange(100.0, 130.0), BpmRange.of('100', 130))

    def test_bounds_are_required_finite_and_ordered(self):
        for minimum, maximum, message in ((None, 130, 'BPM minimum bound is required'),
                                          (100, 'fast', 'BPM maximum bound must be finite'),
                                          (float('inf'), 130, 'BPM minimum bound must be finite'),
                                          (130, 100, 'bpm bounds must be ordered')):
            with self.subTest(minimum=minimum, maximum=maximum):
                with self.assertRaisesRegex(ValueError, message):
                    BpmRange.of(minimum, maximum)

    def test_contains_only_finite_numbers_inside_it(self):
        bpm_range = BpmRange(100, 130)
        self.assertEqual([True, True, False, False, False, False],
                         [bpm_range.contains(value) for value in (100, 130.0, 99.9, float('nan'), True, '120')])


class EligibilityTests(unittest.TestCase):
    def test_a_playable_track_in_range_without_a_bpm_override_is_eligible(self):
        bpm_range = BpmRange(100, 130)
        self.assertTrue(eligible(_Track(), bpm_range))
        for track in (_Track(bpm=140), _Track(active=False), _Track(exists=False), _Track(path='/a\n.flac'),
                      _Track(manual_overrides=('bpm',))):
            with self.subTest(track=track):
                self.assertFalse(eligible(track, bpm_range))

    def test_the_start_track_says_why_it_cannot_open_the_playlist(self):
        bpm_range = BpmRange(100, 130)
        for track, message in ((_Track(catalogued=False), 'start track is not catalogued/playable'),
                               (_Track(manual_overrides=('bpm',)), 'manual BPM override'),
                               (_Track(bpm=90), 'start track BPM is outside requested range')):
            with self.subTest(track=track):
                with self.assertRaisesRegex(ValueError, message):
                    check_start_track(track, bpm_range)


if __name__ == '__main__':
    unittest.main()
