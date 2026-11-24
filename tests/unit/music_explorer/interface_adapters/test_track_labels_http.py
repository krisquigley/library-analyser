"""#243: the track-labels request and response over HTTP."""
import unittest

from music_explorer.application.use_cases.label_tracks.label_tracks import LabelTracksRequest, TrackLabel
from music_explorer.interface_adapters.track_labels_http import label_request_from_query, track_labels_to_http


class TrackLabelsHTTPTests(unittest.TestCase):
    def test_each_track_parameter_names_one_track_in_order(self):
        self.assertEqual(label_request_from_query({'track': ['b', 'a']}), LabelTracksRequest(('b', 'a')))
        self.assertEqual(label_request_from_query({}), LabelTracksRequest(()))

    def test_labels_are_plain_json(self):
        self.assertEqual(track_labels_to_http((TrackLabel('a', '<b>Alpha</b>', 'Synthetic'),)),
                         {'labels': [{'track_id': 'a', 'title': '<b>Alpha</b>', 'artist': 'Synthetic'}]})


if __name__ == '__main__':
    unittest.main()
