"""The indexed graph contract (#291): a node's key travels as an index into a table of keys."""
import json
import unittest

from music_explorer.application.dto.explorer import AxisValue, MoodAxisGraph, MoodAxisNode
from music_explorer.interface_adapters.mood_axis_graph_http import to_indexed_mood_axis_graph_http


def node(suffix, key=None):
    return MoodAxisNode(track_id='sha256:' + suffix * 64, display_label=suffix, x=AxisValue('valence', 0.5, 0.5, 'v'),
                        y=AxisValue('arousal', 0.5, 0.5, 'a'), z=AxisValue('BPM', 120.0, 6.0, 'bpm'), bpm=120.0,
                        genres=(), key=key)


class IndexedGraphKeyTests(unittest.TestCase):
    def test_a_nodes_key_is_an_index_into_the_key_table_and_a_missing_key_is_null(self):
        graph = MoodAxisGraph({}, '', (), (node('a', 'A minor'), node('b'), node('c', 'A minor'), node('d', 'C major')), (), ())
        indexed = to_indexed_mood_axis_graph_http(graph)
        self.assertEqual(indexed['key_table'], ['A minor', 'C major'])
        self.assertEqual([row[13] for row in indexed['nodes']], [0, None, 0, 1])
        json.dumps(indexed, allow_nan=False)


if __name__ == '__main__':
    unittest.main()
