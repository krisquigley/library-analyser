"""#287: a hand-built playlist previews like a recipe's: each track in the listener's order, and each step between."""
import unittest

from music_explorer.application.dto.playlist_preview import PlaylistPreview, PreviewTrack, PreviewTransition
from music_explorer.application.dto.playlists import PlayableTrackCandidate, PlaylistMoodEvidence
from music_explorer.application.use_cases.preview_hand_built_playlist.preview_hand_built_playlist import (
    PreviewHandBuiltPlaylist, PreviewHandBuiltPlaylistRequest,
)
from music_explorer.domain.hand_built_playlist import HandBuiltPlaylistError


def candidate(track_id, bpm=120.0, **fields):
    return PlayableTrackCandidate(track_id, bpm, f'/music/synthetic/{track_id}.flac', **fields)


class FakeLibrary:
    def __init__(self, candidates, evidence):
        self.candidates, self.evidence, self.moods_asked = candidates, evidence, []

    def playlist_export_tracks(self):
        return self.candidates

    def playlist_mood_evidence(self, mood):
        self.moods_asked.append(mood)
        return self.evidence


LIBRARY = FakeLibrary(
    (candidate('a', 120.0, title='Opening', artist='First', key='C', scale='major', key_strength=0.9, duration_seconds=200.0),
     candidate('b', 124.0, title='Middle', artist='Second', key='G', scale='major', key_strength=0.9),
     candidate('c', 100.0, title='Late', key='F#', scale='major', key_strength=0.9, manual_overrides=('energy',)),
     candidate('weak', 120.0, key='D', scale='minor', key_strength=0.1),
     candidate('gone', exists=False), candidate('retired', active=False)),
    {'a': PlaylistMoodEvidence(arousal=4.5, valence=5.25), 'c': PlaylistMoodEvidence(arousal=7.0, valence=3.0)})


def preview(*track_ids, library=LIBRARY):
    return PreviewHandBuiltPlaylist(library, library).execute(PreviewHandBuiltPlaylistRequest(track_ids))


class PreviewHandBuiltPlaylistTest(unittest.TestCase):
    def test_each_track_in_the_listeners_order_with_each_step_between(self):
        self.assertEqual(preview('b', 'a', 'c'), PlaylistPreview(
            tracks=(PreviewTrack('b', 'Middle', 'Second', 124.0, 'G major', '9B', None, None),
                    PreviewTrack('a', 'Opening', 'First', 120.0, 'C major', '8B', 4.5, None, 200.0, valence=5.25),
                    PreviewTrack('c', 'Late', '', 100.0, 'F# major', '2B', None, None)),
            transitions=(PreviewTransition('b', 'a', True, True, -4.0), PreviewTransition('a', 'c', False, False, -20.0)),
            complete=True, warning=None))
        self.assertEqual(LIBRARY.moods_asked[-1], None, 'no mood is held, so none is read')

    def test_a_key_not_known_well_enough_is_shown_but_does_not_judge_the_step(self):
        # As in a recipe's preview (#138): the detected key is shown; only a strong one is mixed by.
        result = preview('a', 'weak')
        self.assertEqual(result.tracks[1].key, 'D minor')
        self.assertEqual(result.transitions, (PreviewTransition('a', 'weak', None, True, 0.0),))

    def test_a_track_no_longer_playable_is_left_out_and_said_so(self):
        result = preview('a', 'gone', 'b', 'retired', 'unknown')
        self.assertEqual([track.track_id for track in result.tracks], ['a', 'b'])
        self.assertEqual(result.transitions, (PreviewTransition('a', 'b', True, True, 4.0),))
        self.assertFalse(result.complete)
        self.assertEqual(result.warning, '3 of its tracks are no longer playable from the library; remove them to download it')

    def test_one_track_no_longer_playable_reads_singular(self):
        self.assertEqual(preview('a', 'gone').warning,
                         '1 of its tracks is no longer playable from the library; remove it to download it')

    def test_the_list_must_keep_the_hand_built_playlist_rules(self):
        for track_ids in ((), ('a', 'a')):
            with self.subTest(track_ids=track_ids), self.assertRaises(HandBuiltPlaylistError):
                preview(*track_ids)


if __name__ == '__main__':
    unittest.main()
