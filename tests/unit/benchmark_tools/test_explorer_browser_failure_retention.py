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


class PartialFocusRetention(unittest.TestCase):
    def test_timeout_retains_partial_motion_without_inventing_completion(self):
        class TimeoutError(Exception): pass
        motion = {'starts': [{'clock': 'browser-performance', 'at_ms': 10}],
                  'cancellations': [{'clock': 'browser-performance', 'at_ms': 20,
                                     'reason': 'user-orbit'}]}
        partial = {'milestones_ms': {'focus_start': 10}, 'requests': [],
                   'focus': {'motion': motion}}
        with patch.object(tool, 'observe', side_effect=TimeoutError('private')), \
                patch.object(Page, 'evaluate', return_value=partial):
            sample = tool.observe_attempt(Page(), 'http://owned.invalid', None, 'pending-then-ready')
        self.assertEqual(sample['outcome'], 'timeout')
        self.assertEqual(sample.get('focus'), partial['focus'])
        self.assertIsNone(sample['milestones_ms']['focus_end'])
        self.assertIsNone(sample['elapsed_ms'])


class LivePage(Page):
    def __init__(self, *, render=True, focus=True, latest=True, consumed=1, retry=False):
        self.result = {'milestones_ms': {'graph_usable_render': 20}, 'requests': [],
                       'render': {'canvas_visible': render, 'nonempty_pixels': True,
                                  'positioned_nodes_visible': True},
                       'focus': {'selected_node_in_view': focus, 'halo_visible': True,
                                 'finite_camera': True, 'consumed_count': consumed,
                                 'projection': {'status': 'observed',
                                                'mesh': {'diameter_px': 10, 'diameter_viewport_fraction': .1},
                                                'halo': {'diameter_px': 20, 'diameter_viewport_fraction': .2}}},
                       'selection': {'accepted': True, 'latest_accepted': latest}}
        if retry:
            self.result['requests'] = [
                {'route': '/api/mood-axis-graph', 'outcome': 'http_error', 'status': 503},
                {'route': '/api/mood-axis-graph', 'outcome': 'ok', 'status': 200}]

    def set_default_timeout(self, value): pass
    def add_init_script(self, value): pass
    def goto(self, *args, **kwargs): pass
    def wait_for_function(self, value): pass
    def locator(self, value): return self
    def get_by_role(self, *args, **kwargs): return self
    def is_visible(self): return True
    @property
    def first(self): return self
    def nth(self, value): return self
    def click(self): pass
    def fill(self, value): pass
    def evaluate(self, script):
        if 'const d=window.__diagnostic, renderer=' in script:
            return self.result
        if '.requests.filter' in script:
            return 1
        return None


class FailureProvenanceRegression(unittest.TestCase):
    def observe(self, page, scenario='pending-then-ready'):
        from threading import Event
        return tool.observe_attempt(page, 'http://owned', Event(), scenario)

    def test_live_invalid_render_has_countable_failure(self):
        sample = self.observe(LivePage(render=False))
        self.assertEqual(sample['outcome'], 'invalid_response')
        self.assertEqual(sample['failures'], [{'flow': 'graph', 'outcome': 'invalid_response'}])

    def test_live_invalid_focus_has_countable_failure(self):
        sample = self.observe(LivePage(focus=False))
        self.assertEqual(sample['outcome'], 'invalid_response')
        self.assertEqual(sample['failures'], [{'flow': 'selection', 'outcome': 'invalid_response'}])

    def test_retry_http_error_and_timeout_each_retained_once(self):
        class TimeoutError(Exception): pass
        page = Page()
        partial = {'requests': [
            {'route': '/api/mood-axis-graph', 'status': 503, 'outcome': 'http_error'},
            {'route': '/api/mood-axis-graph', 'status': 200, 'outcome': 'ok'}],
            'failures': [{'flow': 'graph', 'outcome': 'http_error'}]}
        with patch.object(tool, 'observe', side_effect=TimeoutError('private')), \
                patch.object(page, 'evaluate', return_value=partial):
            sample = self.observe(page, 'graph-failure-retry')
        self.assertEqual(sample['failures'], [
            {'flow': 'graph', 'outcome': 'http_error'},
            {'flow': 'lifecycle', 'outcome': 'timeout'}])

    def test_successful_retry_does_not_double_count_http_failure(self):
        sample = self.observe(LivePage(retry=True), 'graph-failure-retry')
        self.assertEqual(sample['outcome'], 'ok')
        self.assertEqual(sample['failures'], [{'flow': 'graph', 'outcome': 'http_error'}])

    def test_latest_selection_wrong_halo_is_rejected(self):
        sample = self.observe(LivePage(latest=False), 'latest-selection')
        self.assertEqual(sample['outcome'], 'invalid_response')
        self.assertEqual(sample['failures'], [{'flow': 'selection', 'outcome': 'invalid_response'}])

    def test_latest_selection_must_consume_exactly_once(self):
        for count in (0, 2):
            with self.subTest(count=count):
                sample = self.observe(LivePage(consumed=count), 'latest-selection')
                self.assertEqual(sample['outcome'], 'invalid_response')
                self.assertEqual(sample['failures'], [{'flow': 'selection', 'outcome': 'invalid_response'}])

    def test_graph_identity_mismatch_retained_even_after_focus_failure(self):
        sample = {'outcome': 'invalid_response',
                  'failures': [{'flow': 'selection', 'outcome': 'invalid_response'}],
                  'graph_response': {'consumed_sha256': 'wrong'}}
        manifest = {'decoded': {'body_bytes': 10, 'sha256': 'expected'},
                    'encoded': {'body_bytes': 5}, 'counts': {}, 'content_encoding': 'gzip'}
        tool.validate_graph_response(sample, manifest)
        self.assertEqual(sample['failures'], [
            {'flow': 'selection', 'outcome': 'invalid_response'},
            {'flow': 'graph', 'outcome': 'invalid_response'}])

    def test_failure_counts_include_both_invalid_render_and_focus(self):
        from collections import Counter
        sample = self.observe(LivePage(render=False, focus=False))
        counts = Counter(f"{f['flow']}:{f['outcome']}" for f in sample['failures'])
        self.assertEqual(counts, {'graph:invalid_response': 1, 'selection:invalid_response': 1})

    def test_actual_failed_requests_are_not_collapsed_and_raw_fields_are_not_copied(self):
        requests = [{'route': '/api/mood-axis-graph', 'outcome': 'http_error',
                     'status': 503, 'private': 'secret'}] * 2
        self.assertEqual(tool.request_failures(requests), [
            {'flow': 'graph', 'outcome': 'http_error'},
            {'flow': 'graph', 'outcome': 'http_error'}])

    def test_pending_request_is_not_a_connection_failure(self):
        self.assertEqual(tool.request_failures([
            {'route': '/api/mood-axis-graph', 'outcome': 'connection_error', 'elapsed_ms': None}]), [])

    def test_graph_validation_does_not_double_count_prior_render_failure(self):
        sample = {'outcome': 'invalid_response', 'graph_response': {},
                  'failures': [{'flow': 'graph', 'outcome': 'invalid_response'}]}
        manifest = {'decoded': {'body_bytes': 10, 'sha256': 'expected'},
                    'encoded': {'body_bytes': 5}, 'counts': {}, 'content_encoding': 'gzip'}
        tool.validate_graph_response(sample, manifest)
        self.assertEqual(sample['failures'], [{'flow': 'graph', 'outcome': 'invalid_response'}])

    def test_every_scenario_must_consume_focus_exactly_once(self):
        for scenario in tool.SCENARIOS:
            for count in (0, 2):
                with self.subTest(scenario=scenario, count=count):
                    sample = self.observe(LivePage(consumed=count), scenario)
                    self.assertEqual(sample['outcome'], 'invalid_response')
                    self.assertIn({'flow': 'selection', 'outcome': 'invalid_response'}, sample['failures'])
