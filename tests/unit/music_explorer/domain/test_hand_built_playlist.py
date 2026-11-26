"""#277, #287: the rules a hand-built playlist's track IDs keep, shared by its download and its preview."""
import unittest

from music_explorer.domain.hand_built_playlist import (
    MAXIMUM_HAND_BUILT_TRACKS, HandBuiltPlaylistError, hand_built_track_ids,
)


class HandBuiltTrackIdsTest(unittest.TestCase):
    def test_the_listeners_order_is_kept(self):
        self.assertEqual(hand_built_track_ids(['c', 'a', 'b']), ('c', 'a', 'b'))

    def test_a_playlist_names_one_to_the_most_tracks_each_once(self):
        for track_ids, message in (((), 'Add at least one track to the playlist'),
                                   (('a', 'b', 'a'), 'The playlist names a track more than once'),
                                   (('a', ''), 'A track ID must be text of 1 to 256 characters'),
                                   (('a', 7), 'A track ID must be text of 1 to 256 characters'),
                                   (('a\x00',), 'A track ID must be text of 1 to 256 characters'),
                                   (('x' * 257,), 'A track ID must be text of 1 to 256 characters')):
            with self.subTest(track_ids=track_ids), self.assertRaisesRegex(HandBuiltPlaylistError, f'^{message}$'):
                hand_built_track_ids(track_ids)
        most = tuple(f't{number}' for number in range(MAXIMUM_HAND_BUILT_TRACKS))
        self.assertEqual(hand_built_track_ids(most), most)
        with self.assertRaisesRegex(HandBuiltPlaylistError, f'^A playlist holds at most {MAXIMUM_HAND_BUILT_TRACKS} tracks$'):
            hand_built_track_ids(most + ('one-more',))

    def test_its_error_is_a_value_error(self):
        self.assertTrue(issubclass(HandBuiltPlaylistError, ValueError))


if __name__ == '__main__':
    unittest.main()
