"""Failed live observations are retained, never filled with successful times."""
import unittest
from unittest.mock import patch
from tools import explorer_browser_diagnostic as tool


class Page:
    def on(self, event, handler):
        pass

    def evaluate(self, script):
        return {'milestones_ms': {'navigation': 0, 'graph_request': 4},
                'requests': [{'route': '/api/mood-axis-graph', 'outcome': 'timeout'}]}


class FailedAttemptRetention(unittest.TestCase):
    def test_consumed_graph_mismatch_is_not_a_success(self):
        self.assertTrue(hasattr(tool, 'validate_graph_response'), 'validate browser-consumed graph identity')
        manifest = {'decoded': {'body_bytes': 10, 'sha256': 'expected'},
                    'encoded': {'body_bytes': 5}, 'counts': {'nodes': 2, 'links': 1, 'unpositioned': 0},
                    'content_encoding': 'gzip'}
        observed = {'content_encoding': 'gzip', 'content_length': 5, 'consumed_bytes': 10,
                    'consumed_sha256': 'wrong', 'json_counts': manifest['counts']}
        sample = {'outcome': 'ok', 'failures': [], 'graph_response': observed}
        tool.validate_graph_response(sample, manifest)
        self.assertEqual(sample['outcome'], 'invalid_response')
        self.assertEqual(sample['failures'], [{'flow': 'graph', 'outcome': 'invalid_response'}])
        self.assertEqual(sample['graph_response'], observed)

    def test_missing_milestones_are_null_and_request_failure_is_retained(self):
        self.assertTrue(hasattr(tool, 'observe_attempt'), 'retain failed browser attempts')
        with patch.object(tool, 'observe', side_effect=RuntimeError('secret private path')):
            sample = tool.observe_attempt(Page(), 'owned-private-target', None, 'pending-then-ready')
        self.assertEqual(sample['outcome'], 'invalid_response')
        self.assertEqual(sample['milestones_ms']['graph_request'], 4)
        self.assertIsNone(sample['milestones_ms']['graph_body'])
        self.assertIsNone(sample['milestones_ms']['graph_usable_render'])
        self.assertEqual(len(sample['requests']), 1)
        self.assertNotIn('secret', str(sample))
        self.assertIsNone(sample['elapsed_ms'])
