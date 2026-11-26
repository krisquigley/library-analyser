"""#277: a playlist the listener built by hand downloads as an M3U, in their order."""
import unittest

from music_explorer.application.dto.playlists import PlayableTrackCandidate
from music_explorer.application.use_cases.download_hand_built_playlist.download_hand_built_playlist import (
    MAXIMUM_HAND_BUILT_TRACKS, DownloadHandBuiltPlaylist, DownloadHandBuiltPlaylistRequest, HandBuiltPlaylistRequestError,
)


def candidate(track_id, **flags):
    return PlayableTrackCandidate(track_id, 120.0, f'/music/synthetic/{track_id}.flac', **flags)


class FakePlaylistTracks:
    def __init__(self, *candidates):
        self.candidates = candidates

    def playlist_export_tracks(self):
        return self.candidates


LIBRARY = FakePlaylistTracks(candidate('a'), candidate('b'), candidate('c'), candidate('gone', exists=False),
                             candidate('retired', active=False), candidate('uncatalogued', catalogued=False))


def download(*track_ids, tracks=LIBRARY):
    return DownloadHandBuiltPlaylist(tracks).execute(DownloadHandBuiltPlaylistRequest(track_ids))


class DownloadHandBuiltPlaylistTest(unittest.TestCase):
    def test_the_tracks_are_listed_in_the_order_the_listener_built_them(self):
        playlist = download('c', 'a', 'b')
        self.assertEqual(playlist.content, '#EXTM3U\n/music/synthetic/c.flac\n/music/synthetic/a.flac\n/music/synthetic/b.flac\n')
        self.assertEqual(playlist.track_ids, ('c', 'a', 'b'))
        self.assertIsNone(playlist.warning)

    def test_a_playlist_names_one_to_the_most_tracks_each_once(self):
        for track_ids, message in (((), 'Add at least one track to the playlist'),
                                   (('a', 'b', 'a'), 'The playlist names a track more than once'),
                                   (('a', ''), 'A track ID must be text of 1 to 256 characters'),
                                   (('a', 7), 'A track ID must be text of 1 to 256 characters'),
                                   (('x' * 257,), 'A track ID must be text of 1 to 256 characters')):
            with self.subTest(track_ids=track_ids), self.assertRaisesRegex(HandBuiltPlaylistRequestError, f'^{message}$'):
                download(*track_ids)
        many = tuple(f't{number}' for number in range(MAXIMUM_HAND_BUILT_TRACKS + 1))
        tracks = FakePlaylistTracks(*(candidate(track_id) for track_id in many))
        self.assertEqual(len(download(*many[:-1], tracks=tracks).track_ids), MAXIMUM_HAND_BUILT_TRACKS)
        with self.assertRaisesRegex(HandBuiltPlaylistRequestError, f'^A playlist holds at most {MAXIMUM_HAND_BUILT_TRACKS} tracks$'):
            download(*many, tracks=tracks)

    def test_a_track_that_cannot_be_played_from_the_library_is_refused_by_name_of_its_place(self):
        for missing in ('unknown', 'gone', 'retired', 'uncatalogued'):
            with self.subTest(missing=missing), self.assertRaisesRegex(
                    HandBuiltPlaylistRequestError, '^Track 2 of the playlist is no longer playable from the library; remove it and try again$'):
                download('a', missing, 'b')


if __name__ == '__main__':
    unittest.main()
