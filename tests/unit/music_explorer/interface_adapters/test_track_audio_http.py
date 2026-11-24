"""Issue #258: the track-audio request and response over HTTP: one track, its media type, and the bytes asked for."""
import unittest

from music_explorer.application.use_cases.listen_to_track.listen_to_track import TrackAudioRequestError
from music_explorer.interface_adapters.track_audio_http import (
    TrackAudioFormatError, TrackAudioRangeError, audio_media_type, byte_range, track_audio_request_from_query)


class TrackAudioRequestTests(unittest.TestCase):
    def test_the_query_names_exactly_one_track(self):
        self.assertEqual('sha256:a', track_audio_request_from_query({'track': ['sha256:a']}).track_id)
        for values in ({}, {'track': ['a', 'b']}):
            with self.subTest(values=values), self.assertRaisesRegex(TrackAudioRequestError, 'Name one track to listen to'):
                track_audio_request_from_query(values)


class AudioMediaTypeTests(unittest.TestCase):
    def test_the_media_type_follows_the_file_extension_whatever_its_case(self):
        for location, media_type in (('/l/a.mp3', 'audio/mpeg'), ('/l/a.FLAC', 'audio/flac'), ('/l/a.m4a', 'audio/mp4'),
                                     ('/l/a.ogg', 'audio/ogg'), ('/l/a.opus', 'audio/ogg'), ('/l/a.wav', 'audio/wav'),
                                     ('/l/a.aiff', 'audio/aiff'), ('/l/a.aif', 'audio/aiff')):
            with self.subTest(location=location):
                self.assertEqual(media_type, audio_media_type(location))

    def test_an_unknown_format_is_refused_without_naming_the_file(self):
        with self.assertRaises(TrackAudioFormatError) as refused:
            audio_media_type('/private/library/a.xyz')
        self.assertEqual('This audio format cannot be played in the browser', str(refused.exception))


class ByteRangeTests(unittest.TestCase):
    def test_no_range_asks_for_the_whole_file(self):
        self.assertIsNone(byte_range(None, 1000))

    def test_a_range_is_inclusive_and_an_open_end_runs_to_the_last_byte(self):
        self.assertEqual((0, 99), byte_range('bytes=0-99', 1000))
        self.assertEqual((500, 999), byte_range('bytes=500-', 1000))
        self.assertEqual((900, 999), byte_range('bytes=-100', 1000), 'the last hundred bytes')
        self.assertEqual((10, 999), byte_range('bytes=10-5000', 1000), 'an end past the file stops at its last byte')

    def test_a_range_that_cannot_be_served_is_refused(self):
        for header in ('bytes=1000-', 'bytes=5-2', 'bytes=-0', 'bytes=a-b', 'items=0-1', 'bytes=0-1,4-5'):
            with self.subTest(header=header), self.assertRaises(TrackAudioRangeError):
                byte_range(header, 1000)


if __name__ == '__main__':
    unittest.main()
