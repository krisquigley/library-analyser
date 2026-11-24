"""Issue #258: listen to a track from the Explorer: its available audio file, read as it is."""
import unittest

from music_explorer.application.use_cases.listen_to_track.listen_to_track import (
    ListenToTrack, ListenToTrackRequest, TrackAudio, TrackAudioRequestError, TrackAudioUnavailableError)


class _Locations:
    def __init__(self, locations):
        self.locations = locations
        self.asked = []

    def first_available_location(self, track_id):
        self.asked.append(track_id)
        return self.locations.get(track_id)


class ListenToTrackTests(unittest.TestCase):
    def test_a_track_is_heard_from_its_first_available_file(self):
        locations = _Locations({'sha256:a': '/library/a.flac'})
        self.assertEqual(TrackAudio('sha256:a', '/library/a.flac'),
                         ListenToTrack(locations).execute(ListenToTrackRequest('sha256:a')))

    def test_a_track_without_an_available_file_cannot_be_heard(self):
        with self.assertRaisesRegex(TrackAudioUnavailableError, 'This track has no available audio file'):
            ListenToTrack(_Locations({})).execute(ListenToTrackRequest('sha256:b'))

    def test_a_malformed_track_id_is_refused_before_anything_is_read(self):
        locations = _Locations({})
        for track_id in ('', ' ', 'a' * 257, 'a\x00b'):
            with self.subTest(track_id=track_id), self.assertRaisesRegex(TrackAudioRequestError, 'Name one track to listen to'):
                ListenToTrack(locations).execute(ListenToTrackRequest(track_id))
        self.assertEqual([], locations.asked)


if __name__ == '__main__':
    unittest.main()
