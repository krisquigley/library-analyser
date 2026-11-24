"""#243: the graph labels a selected track and its neighbours with their titles and artists, read by ID."""
import unittest

from music_explorer.application.dto.explorer import ExplorerTrackSummary
from music_explorer.application.use_cases.label_tracks.label_tracks import (
    MAXIMUM_TRACKS_PER_LABEL_REQUEST, LabelTracks, LabelTracksRequest, TrackLabel, TrackLabelRequestError)


class FakeTrackSummaries:
    def __init__(self, *summaries):
        self.summaries = {summary.handle: summary for summary in summaries}
        self.asked = []

    def track_summaries(self, track_ids):
        self.asked.append(track_ids)
        return tuple(self.summaries[track_id] for track_id in track_ids if track_id in self.summaries)


def summary(track_id, title, artist):
    return ExplorerTrackSummary(track_id, title, artist, f'{track_id}.flac', 1)


class LabelTracksTests(unittest.TestCase):
    def test_labels_come_back_in_the_order_asked_and_unknown_tracks_are_left_out(self):
        tracks = FakeTrackSummaries(summary('a', 'Alpha', 'Synthetic one'), summary('b', 'Beta', 'Synthetic two'))
        labels = LabelTracks(tracks).execute(LabelTracksRequest(('b', 'gone', 'a')))
        self.assertEqual(labels, (TrackLabel('b', 'Beta', 'Synthetic two'), TrackLabel('a', 'Alpha', 'Synthetic one')))
        self.assertEqual(tracks.asked, [('b', 'gone', 'a')])

    def test_a_request_names_between_one_and_the_maximum_distinct_track_ids(self):
        tracks = FakeTrackSummaries()
        too_many = tuple(f't{n}' for n in range(MAXIMUM_TRACKS_PER_LABEL_REQUEST + 1))
        for track_ids, message in (((), 'Name at least one track'),
                                   (too_many, f'Name at most {MAXIMUM_TRACKS_PER_LABEL_REQUEST} tracks'),
                                   (('a', 'a'), 'Name each track once'),
                                   (('',), 'A track ID must be text of 1 to 256 characters'),
                                   (('x' * 257,), 'A track ID must be text of 1 to 256 characters'),
                                   (('a\x00',), 'A track ID must be text of 1 to 256 characters'),
                                   ((7,), 'A track ID must be text of 1 to 256 characters')):
            with self.subTest(message=message):
                with self.assertRaisesRegex(TrackLabelRequestError, message):
                    LabelTracks(tracks).execute(LabelTracksRequest(track_ids))
        self.assertEqual(tracks.asked, [])
        self.assertEqual(MAXIMUM_TRACKS_PER_LABEL_REQUEST, 100)


if __name__ == '__main__':
    unittest.main()
