"""Focused public regressions for benchmark rank and indexed-axis integrity."""
import copy
import hashlib
import json
import unittest

from music_explorer.interface_adapters.mood_axis_graph_http import to_indexed_mood_axis_graph_http
from tests.acceptance import test_mood_axis_graph_indexed_http_red as public_graph_fixture
from tools.graph_read_benchmark import measure_samples, nearest_rank


class SyntheticResponse:
    status = 200

    def __init__(self, body):
        self.body = body

    def read(self):
        return self.body

    def getheader(self, name, default=None):
        return str(len(self.body)) if name == 'Content-Length' else default


class NearestRankRegressionTests(unittest.TestCase):
    def test_exact_integer_rank_does_not_round_up_from_binary_float_error(self):
        self.assertEqual(nearest_rank(range(1, 26), 28), 7)

    def test_exact_fractional_percentile_rank_does_not_round_up(self):
        self.assertEqual(nearest_rank(range(1, 126), 7.2), 9)

    def test_nonintegral_rank_still_rounds_up(self):
        self.assertEqual(nearest_rank(range(1, 26), 28.1), 8)


class IndexedAxisRegressionTests(unittest.TestCase):
    def setUp(self):
        graph = public_graph_fixture.IndexedMoodAxisGraphHttpContractRedTests()._synthetic_repeated_string_graph(3)
        self.payload = to_indexed_mood_axis_graph_http(graph)

    def measure(self, payload):
        body = json.dumps(payload, sort_keys=True, ensure_ascii=False, allow_nan=False).encode('utf-8')
        return measure_samples(
            [lambda: SyntheticResponse(body)],
            expected={'sha256': hashlib.sha256(body).hexdigest(),
                      'counts': {'nodes': 3, 'links': 2, 'unpositioned': 0}},
            db_fingerprint=lambda: 'unchanged-public-synthetic',
        )

    def test_real_mapper_axes_are_accepted(self):
        self.assertEqual(self.measure(self.payload)['succeeded'], 1)

    def test_reordered_valid_axes_are_accepted(self):
        payload = copy.deepcopy(self.payload)
        payload['axis'].reverse()
        self.assertEqual(self.measure(payload)['succeeded'], 1)

    def test_unknown_unique_axis_key_is_rejected_even_with_matching_hash(self):
        payload = copy.deepcopy(self.payload)
        payload['axis'][1]['key'] = 'unknown-axis'
        report = self.measure(payload)
        self.assertEqual(report['samples'][0]['outcome'], 'invalid_v3')
        self.assertEqual(report['succeeded'], 0)

    def test_duplicate_axis_keys_are_rejected_even_with_matching_hash(self):
        payload = copy.deepcopy(self.payload)
        payload['axis'][1]['key'] = payload['axis'][0]['key']
        report = self.measure(payload)
        self.assertEqual(report['samples'][0]['outcome'], 'invalid_v3')
        self.assertEqual(report['succeeded'], 0)

    def test_empty_axis_fields_are_rejected_even_with_matching_hash(self):
        for index in range(3):
            for field in ('key', 'label', 'scale'):
                with self.subTest(index=index, field=field):
                    payload = copy.deepcopy(self.payload)
                    payload['axis'][index][field] = ''
                    report = self.measure(payload)
                    self.assertEqual(report['samples'][0]['outcome'], 'invalid_v3')
                    self.assertEqual(report['succeeded'], 0)


if __name__ == '__main__':
    unittest.main()
