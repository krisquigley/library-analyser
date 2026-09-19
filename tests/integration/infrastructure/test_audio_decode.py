from pathlib import Path
import os
import shutil
import subprocess
import tempfile
import unittest
import wave

from music_analyzer.application.dto.analysis import AnalysisError, AudioSource
from music_analyzer.infrastructure.audio.ffmpeg import FFmpegDecoder


@unittest.skipUnless(os.environ.get('RUN_FFMPEG_TESTS') == '1' and shutil.which('ffmpeg'),
                     'requires RUN_FFMPEG_TESTS=1 and existing FFmpeg executable')
class FFmpegDecoderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / '音 space.wav'
        with wave.open(str(self.source), 'wb') as stream:
            stream.setparams((1, 2, 44100, 0, 'NONE', 'not compressed'))
            stream.writeframes(b'\x00\x00' * 44100)

    def test_real_flac_mp3_and_m4a_decode_and_cleanup(self):
        original = self.source.read_bytes()
        for extension in ('flac', 'mp3', 'm4a'):
            path = self.root / f'音 space.{extension}'
            subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-i', str(self.source), str(path)],
                           check=True, timeout=10, capture_output=True)
            before = path.read_bytes()
            with FFmpegDecoder().decode(AudioSource(str(path)), 2) as audio:
                decoded = Path(audio.handle)
                self.assertTrue(decoded.is_file())
                self.assertEqual(audio.sample_rate, 44100)
                self.assertAlmostEqual(audio.duration, 1, delta=0.1)
                self.assertEqual(decoded.stat().st_size, round(audio.duration * 44100) * 4)
            self.assertFalse(decoded.exists())
            self.assertEqual(path.read_bytes(), before)
        self.assertEqual(self.source.read_bytes(), original)

    def test_rejects_over_limit_instead_of_yielding_truncated_audio(self):
        with self.assertRaisesRegex(AnalysisError, 'duration limit'):
            with FFmpegDecoder().decode(AudioSource(str(self.source)), 0.5):
                self.fail('must not yield truncated audio')

    def test_missing_corrupt_and_empty_audio_are_actionable_failures(self):
        corrupt = self.root / 'corrupt.flac'
        corrupt.write_bytes(b'not audio')
        for path in (self.root / 'missing.flac', corrupt):
            with self.subTest(path=path), self.assertRaises(AnalysisError):
                with FFmpegDecoder().decode(AudioSource(str(path)), 2):
                    self.fail('must not yield invalid audio')

    def test_cleanup_on_consumer_error_and_interrupt(self):
        for error in (RuntimeError('consumer failed'), KeyboardInterrupt()):
            with self.assertRaises(type(error)):
                with FFmpegDecoder().decode(AudioSource(str(self.source)), 2) as audio:
                    decoded = Path(audio.handle)
                    raise error
            self.assertFalse(decoded.exists())

    def test_missing_executable_translates_failure(self):
        with self.assertRaises(AnalysisError):
            with FFmpegDecoder(executable='/does-not-exist/ffmpeg').decode(AudioSource(str(self.source)), 2):
                self.fail('must not yield audio')

    def test_snapshot_rejects_changed_expected_source_and_bounds_input(self):
        with self.assertRaisesRegex(AnalysisError, 'identity'):
            with FFmpegDecoder().decode(AudioSource(str(self.source), 'sha256:' + '0' * 64), 2):
                self.fail('wrong source')
        with self.assertRaisesRegex(AnalysisError, 'snapshot limit'):
            with FFmpegDecoder(max_source_bytes=10).decode(AudioSource(str(self.source)), 2):
                self.fail('oversized snapshot')

    def test_decode_uses_private_snapshot_even_if_source_changes(self):
        from unittest.mock import patch
        import hashlib
        original = self.source.read_bytes()
        real_popen = subprocess.Popen
        def mutate(command, **kwargs):
            self.assertNotEqual(command[command.index('-i') + 1], str(self.source))
            self.source.write_bytes(b'changed while decoding')
            return real_popen(command, **kwargs)
        with patch('music_analyzer.infrastructure.audio.ffmpeg.subprocess.Popen', side_effect=mutate):
            with FFmpegDecoder().decode(AudioSource(str(self.source), 'sha256:' + hashlib.sha256(original).hexdigest()), 2) as audio:
                self.assertTrue(audio.identity)
                self.assertAlmostEqual(audio.duration, 1)
