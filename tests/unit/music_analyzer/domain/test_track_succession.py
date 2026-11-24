"""Issue #223: which new file continues which departed track after a tags-only change."""
import unittest

from music_analyzer.domain.track_succession import StreamedTrack, TrackSuccession, tags_only_successions

AUDIO_A, AUDIO_B = 'a' * 64, 'b' * 64


def track(name, audio):
    return StreamedTrack(f'sha256:{name * 64}', audio)


class TagsOnlySuccessionTests(unittest.TestCase):
    def test_a_new_file_continues_the_departed_track_with_the_same_audio(self):
        old, new = track('1', AUDIO_A), track('2', AUDIO_A)
        self.assertEqual(tags_only_successions(arrivals=(new,), departures=(old,)),
                         (TrackSuccession(old.track_id, new.track_id, AUDIO_A),))

    def test_different_audio_is_never_a_succession(self):
        self.assertEqual(tags_only_successions(arrivals=(track('2', AUDIO_B),), departures=(track('1', AUDIO_A),)), ())

    def test_an_ambiguous_match_on_either_side_carries_nothing_over(self):
        old, other_old = track('1', AUDIO_A), track('3', AUDIO_A)
        new, other_new = track('2', AUDIO_A), track('4', AUDIO_A)
        self.assertEqual(tags_only_successions(arrivals=(new,), departures=(old, other_old)), ())
        self.assertEqual(tags_only_successions(arrivals=(new, other_new), departures=(old,)), ())

    def test_each_audio_stream_is_paired_on_its_own_in_a_stable_order(self):
        pairs = tags_only_successions(arrivals=(track('4', AUDIO_B), track('2', AUDIO_A)),
                                      departures=(track('1', AUDIO_A), track('3', AUDIO_B)))
        self.assertEqual([(p.predecessor_id[7], p.successor_id[7]) for p in pairs], [('1', '2'), ('3', '4')])

    def test_a_track_cannot_succeed_itself(self):
        same = track('1', AUDIO_A)
        self.assertEqual(tags_only_successions(arrivals=(same,), departures=(same,)), ())


if __name__ == '__main__':
    unittest.main()
