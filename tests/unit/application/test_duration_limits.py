import unittest

from music_analyzer.application.dto.analysis import AnalysisError, AudioSource
from music_analyzer.domain.analysis import MAX_ANALYSIS_DURATION_SECONDS
from music_analyzer.infrastructure.audio.ffmpeg import FFmpegDecoder


class DurationLimitTests(unittest.TestCase):
    def test_public_cap_allows_required_long_track_window_and_rejects_above_bound(self):
        self.assertGreaterEqual(MAX_ANALYSIS_DURATION_SECONDS, 4757)
        with self.assertRaisesRegex(AnalysisError, str(MAX_ANALYSIS_DURATION_SECONDS)):
            with FFmpegDecoder().decode(AudioSource('/does/not/exist.flac'), MAX_ANALYSIS_DURATION_SECONDS + 1):
                self.fail('duration bound should be checked before I/O')
