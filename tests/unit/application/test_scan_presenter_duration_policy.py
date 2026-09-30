import json
import unittest

from music_analyzer.application.dto.catalogue import Inventory, ScanReport, ScannedFile, TrackMetadata
from music_analyzer.domain.catalogue import FileIdentity
from music_analyzer.interface_adapters.presenters.catalogue import present_scan


class ScanPresenterDurationPolicyTests(unittest.TestCase):
    def test_counts_and_warns_about_untrusted_duration_sources(self):
        files = (
            ScannedFile('/music/good.flac', FileIdentity('a' * 64, 1), 1, 'flac', TrackMetadata(duration_seconds=60.0, duration_source='mutagen')),
            ScannedFile('/music/textual.flac', FileIdentity('b' * 64, 1), 1, 'flac', TrackMetadata(duration_seconds=60.0, duration_source='textual-tag')),
            ScannedFile('/music/blank.flac', FileIdentity('c' * 64, 1), 1, 'flac', TrackMetadata(duration_seconds=60.0, duration_source='')),
            ScannedFile('/music/zero.flac', FileIdentity('d' * 64, 1), 1, 'flac', TrackMetadata(duration_seconds=0.0, duration_source='ffprobe')),
        )
        report = ScanReport('/music', files, (), True, ())

        text = present_scan(report)
        payload = json.loads(present_scan(report, as_json=True))

        self.assertIn('1 duration exclusions, 2 unknown durations', text)
        self.assertIn('WARNING /music/textual.flac: duration unverified', text)
        self.assertIn('WARNING /music/blank.flac: duration unverified', text)
        self.assertIn('WARNING /music/zero.flac: duration invalid', text)
        self.assertEqual(payload['active_exclusion_count'], 1)
        self.assertEqual(payload['duration_unknown_count'], 2)
        self.assertEqual(payload['files'][1]['active_exclusion_reason'].split(';')[0], 'duration unverified')

    def test_threshold_boundary_warning_does_not_display_rounded_threshold_as_observed_duration(self):
        files = (
            ScannedFile('/music/exact.flac', FileIdentity('e' * 64, 1), 1, 'flac', TrackMetadata(duration_seconds=1200.0, duration_source='mutagen')),
            ScannedFile('/music/just-over.flac', FileIdentity('f' * 64, 1), 1, 'flac', TrackMetadata(duration_seconds=1200.000001, duration_source='ffprobe')),
        )
        report = ScanReport('/music', files, (), True, ())

        text = present_scan(report)
        payload = json.loads(present_scan(report, as_json=True))
        warning = payload['files'][1]['active_exclusion_reason']

        self.assertNotIn('WARNING /music/exact.flac', text)
        self.assertIn('1 duration exclusions, 0 unknown durations', text)
        self.assertIn('duration exceeds 1200.0s', warning)
        self.assertNotIn('1200.000s', warning)
        self.assertIn(f'WARNING /music/just-over.flac: {warning}', text)


if __name__ == '__main__':
    unittest.main()
