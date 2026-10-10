"""Tiny observer correlation contracts; not real browser evidence."""
import unittest
from unittest.mock import Mock
from tools import explorer_db_detail_browser as observer


class WriterObserverTests(unittest.TestCase):
    def raw(self):
        return {'initial_summary_requests': 0, 'requests': [
            {'route': '/api/current', 'method': 'POST', 'request_id': 'request-1',
             'request_handle': 'transient', 'response_handle': 'transient', 'status': 200,
             'request_ms': 2, 'headers_ms': 3, 'body_ms': 4, 'parse_ms': 5, 'sequence': 1},
            {'route': '/api/tracks/<id>', 'method': 'GET', 'request_id': 'request-2',
             'request_handle': 'transient', 'response_handle': 'transient', 'status': 200,
             'request_ms': 6, 'headers_ms': 7, 'body_ms': 8, 'parse_ms': 9, 'sequence': 1}],
            'selections': [{'sequence': 1, 'intended_handle': 'transient', 'is_trusted': True,
                            'receipt_ms': 1, 'detail_presented': True,
                            'detail_dom_ready_ms': 10, 'detail_next_frame_ms': 11}]}

    def test_correlates_real_post_get_and_dom_without_retaining_handles(self):
        bridge = observer.bridge_observation(self.raw(), {'manifest': {}})
        self.assertEqual(len(bridge['selections']), 1)
        selected = bridge['selections'][0]
        self.assertTrue(selected['post']['accepted'])
        self.assertTrue(selected['detail']['identity_matches'])
        self.assertTrue(selected['detail_presented'])
        self.assertIsNone(selected['dom_identity_matches'])
        self.assertEqual(bridge['unrelated_detail_requests'], 0)
        self.assertNotIn('transient', str(bridge))

    def test_dto_handle_is_request_identity_but_never_dom_identity(self):
        raw = self.raw()
        raw['selections'][0]['detail_presented'] = False
        raw['selections'][0]['dom_handle'] = 'transient'
        bridge = observer.bridge_observation(raw, {'manifest': {}})
        self.assertTrue(bridge['selections'][0]['detail']['identity_matches'])
        self.assertIsNone(bridge['selections'][0]['dom_identity_matches'])
        self.assertFalse(bridge['selections'][0]['detail_presented'])

    def test_rejection_or_untrusted_input_is_not_an_accepted_selection(self):
        for fault in ('rejected', 'untrusted', 'dom-mismatch'):
            raw = self.raw()
            if fault == 'rejected': raw['requests'][0]['status'] = 409
            if fault == 'untrusted': raw['selections'][0]['is_trusted'] = False
            if fault == 'dom-mismatch': raw['selections'][0]['detail_presented'] = False
            bridge = observer.bridge_observation(raw, {'manifest': {}})
            self.assertEqual(len(bridge['selections']), 1)
            selected = bridge['selections'][0]
            self.assertFalse(selected['post']['accepted'] and selected['detail']['identity_matches']
                             and selected['detail_presented'])

    def test_timeout_keeps_request_receipt_without_inventing_completion(self):
        raw = self.raw()
        raw['requests'] = raw['requests'][:1]
        for key in ('headers_ms', 'body_ms', 'parse_ms', 'status', 'response_handle'):
            raw['requests'][0].pop(key)
        raw['selections'][0].pop('detail_dom_ready_ms')
        raw['selections'][0].pop('detail_next_frame_ms')
        bridge = observer.bridge_observation(raw, {'manifest': {}})
        self.assertEqual(len(bridge['selections']), 1)
        selected = bridge['selections'][0]
        self.assertEqual(selected['receipt_ms'], 1)
        self.assertEqual(selected['post']['request_ms'], 2)
        self.assertIsNone(selected['post']['accepted'])
        self.assertIsNone(selected['detail'])
        self.assertIsNone(selected['detail_next_frame_ms'])

    def test_duplicate_or_unrelated_detail_is_not_silently_correlated(self):
        raw = self.raw()
        duplicate = dict(raw['requests'][1], request_handle='other', request_id='request-3')
        raw['requests'].append(duplicate)
        bridge = observer.bridge_observation(raw, {'manifest': {}})
        self.assertEqual(bridge['unrelated_detail_requests'], 1)
        self.assertFalse(bridge['selections'][0]['detail']['identity_matches'])

    def test_failed_lifecycle_retains_partial_selection_and_classifies_timeout(self):
        page = Mock()
        page.goto.side_effect = TimeoutError('private host/path must not escape')
        page.evaluate.return_value = self.raw()
        sample = observer.observe_writer_attempt(page, 'http://127.0.0.1:1',
                                                  'pending-then-ready', 'verified', {'manifest': {}})
        self.assertEqual(sample['outcome'], 'timeout')
        self.assertIsNone(sample['elapsed_ms'])
        self.assertEqual(sample['detail_bridge']['selections'][0]['receipt_ms'], 1)
        self.assertNotIn('private host', str(sample))
        self.assertNotIn('transient', str(sample))

    def test_graph_consumed_identity_is_separate_from_fixture_semantics(self):
        raw = self.raw()
        raw.update(graph_sha256='a' * 64, graph_bytes=23, graph_value={'nodes': []},
                   graph_counts={'nodes': 0, 'links': 0, 'unpositioned': 0})
        fixture = {'manifest': {'graph': {'counts': raw['graph_counts']}},
                   'graph_body': b'{"nodes":[]}'}
        bridge = observer.bridge_observation(raw, fixture)
        self.assertTrue(bridge['graph_matches_fixture'])
        self.assertEqual(bridge['graph_consumed'], {'sha256': 'a' * 64, 'body_bytes': 23})
        raw['graph_value'] = {'nodes': ['wrong']}
        self.assertFalse(observer.bridge_observation(raw, fixture)['graph_matches_fixture'])

    def test_unsupported_contention_or_native_mode_is_not_relabelled_writer_success(self):
        for scenario, mode in (('during-consumption', 'verified'), ('pending-then-ready', 'native-json')):
            page = Mock()
            page.evaluate.return_value = self.raw()
            sample = observer.observe_writer_attempt(page, 'http://127.0.0.1:1', scenario, mode,
                                                       {'manifest': {}})
            self.assertEqual(sample['outcome'], 'invalid_response')
            page.goto.assert_not_called()

    def test_probe_installation_failure_is_retained_as_an_attempt(self):
        page = Mock()
        page.add_init_script.side_effect = RuntimeError('private setup details')
        page.evaluate.return_value = {}
        sample = observer.observe_writer_attempt(page, 'http://127.0.0.1:1', 'pending-then-ready',
                                                   'verified', {'manifest': {}})
        self.assertEqual(sample['outcome'], 'invalid_response')
        self.assertEqual(sample['detail_bridge']['selections'], [])
        self.assertNotIn('private setup details', str(sample))

    def test_writer_fault_scenarios_install_single_explicit_route_fault(self):
        for scenario in ('rejected-post', 'detail-timeout'):
            page = Mock()
            page.goto.side_effect = TimeoutError()
            page.evaluate.return_value = {}
            sample = observer.observe_writer_attempt(page, 'http://127.0.0.1:1', scenario,
                                                       'verified', {'manifest': {}})
            page.route.assert_called_once()
            self.assertEqual(page.route.call_args.kwargs['times'], 1)
            self.assertEqual(sample['outcome'], 'timeout')

    def test_actual_renderer_metadata_is_allowlisted_without_unmasked_vendor_strings(self):
        raw = self.raw()
        raw['webgl_context'] = {'api_version': 'webgl2', 'vendor': 'WebKit',
                                'renderer': 'WebKit WebGL', 'implementation': 'software-swiftshader',
                                'unmasked': 'private hardware description'}
        page = Mock()
        page.goto.side_effect = TimeoutError()
        page.evaluate.return_value = raw
        sample = observer.observe_writer_attempt(page, 'http://127.0.0.1:1', 'pending-then-ready',
                                                   'verified', {'manifest': {}})
        self.assertEqual(sample.get('webgl_context', {}).get('implementation'), 'software-swiftshader')
        self.assertNotIn('private hardware', str(sample))

    def test_graph_retry_evidence_comes_from_distinct_observed_requests(self):
        raw = self.raw()
        raw['requests'].extend([
            {'route': '/api/mood-axis-graph', 'status': 503},
            {'route': '/api/mood-axis-graph', 'status': 200}])
        raw['graph_retry_count'] = 1
        bridge = observer.bridge_observation(raw, {'manifest': {}})
        self.assertEqual(bridge.get('graph_retry_count'), 1)
        self.assertEqual(bridge.get('graph_attempt_outcomes'), ['http_error', 'ok'])
        raw.pop('graph_retry_count')
        self.assertEqual(observer.bridge_observation(raw, {'manifest': {}}).get('graph_retry_count'), 0)

    def test_graph_fault_route_matches_actual_graph_query_string(self):
        import fnmatch
        page = Mock()
        page.goto.side_effect = TimeoutError()
        page.evaluate.return_value = {}
        observer.observe_writer_attempt(page, 'http://127.0.0.1:1', 'graph-failure-retry',
                                        'verified', {'manifest': {}})
        pattern = page.route.call_args.args[0]
        self.assertTrue(fnmatch.fnmatch('http://127.0.0.1:1/api/mood-axis-graph?layout=mood', pattern))

    def test_graph_fault_injection_is_observed_not_inferred_from_scenario(self):
        page = Mock()
        page.evaluate.return_value = {}
        def dispatch(*args, **kwargs):
            route = Mock()
            route.request.url = 'http://127.0.0.1:1/api/mood-axis-graph?layout=mood'
            page.route.call_args.args[1](route)
            raise TimeoutError()
        page.goto.side_effect = dispatch
        sample = observer.observe_writer_attempt(page, 'http://127.0.0.1:1', 'graph-failure-retry',
                                                   'verified', {'manifest': {}})
        self.assertIs(sample.get('graph_fault_injected'), True)
        page.goto.side_effect = TimeoutError()
        sample = observer.observe_writer_attempt(page, 'http://127.0.0.1:1', 'graph-failure-retry',
                                                   'verified', {'manifest': {}})
        self.assertIs(sample.get('graph_fault_injected'), False)

    def test_repeated_loading_calls_preserve_first_dom_and_next_frame_observation(self):
        import json
        import shutil
        import subprocess
        node = shutil.which('node')
        if node is None:
            self.skipTest('Node required for real observer wrapper contract')
        script = """
        let time=0;const frames=[];
        global.performance={now:()=>++time};
        global.window={__dbBridge:{selections:[{sequence:1}]}};
        global.document={getElementById:()=>({getAttribute:()=> 'false'})};
        global.requestAnimationFrame=callback=>frames.push(callback);
        global.renderDetailLoading=()=>null;global.renderDetail=()=>null;
        (WRAPPER)();
        renderDetailLoading();const first=window.__dbBridge.selections[0].loading_dom_ms;
        renderDetailLoading();frames.forEach(callback=>callback());
        console.log(JSON.stringify({first,selected:window.__dbBridge.selections[0],frames:frames.length}));
        """.replace('WRAPPER', observer.WRAP_DETAIL)
        result = subprocess.run([node, '-e', script], capture_output=True, text=True,
                                timeout=5, check=True)
        observed = json.loads(result.stdout)
        self.assertEqual(observed['selected']['loading_dom_ms'], observed['first'])
        self.assertEqual(observed['frames'], 1)
        self.assertFalse(observed['selected']['loading_frame_was_busy'])
        self.assertGreater(observed['selected']['loading_frame_ms'], observed['first'])

    def test_missing_http_status_is_not_published_as_an_http_error(self):
        for failed, expected in ((True, 'connection_error'), (False, 'unknown')):
            raw = self.raw()
            raw['requests'] = [{'route': '/api/tracks/<id>', 'method': 'GET',
                                'request_ms': 3, 'status': None, 'failed': failed}]
            page = Mock()
            page.goto.side_effect = TimeoutError()
            page.evaluate.return_value = raw
            sample = observer.observe_writer_attempt(page, 'http://127.0.0.1:1', 'pending-then-ready',
                                                       'verified', {'manifest': {}})
            self.assertEqual(sample['requests'][0]['outcome'], expected)

    def test_injected_transport_timeout_is_classified_separately_from_http_response(self):
        raw = self.raw()
        raw['requests'] = [{'route': '/api/tracks/<id>', 'method': 'GET',
                            'request_ms': 3, 'failed': True}]
        page = Mock()
        page.evaluate.return_value = raw
        def dispatch(*args, **kwargs):
            route = Mock()
            route.request.url = 'http://127.0.0.1:1/api/tracks/sha256%3Atest'
            page.route.call_args.args[1](route)
            raise TimeoutError()
        page.goto.side_effect = dispatch
        sample = observer.observe_writer_attempt(page, 'http://127.0.0.1:1', 'detail-timeout',
                                                   'verified', {'manifest': {}})
        self.assertEqual(sample['requests'][0]['outcome'], 'timeout')
        self.assertEqual(sample['requests'][0]['status'], None)

    def test_bounded_wait_timeout_is_a_page_safety_setting_not_a_speed_assertion(self):
        page = Mock()
        page.goto.side_effect = TimeoutError()
        page.evaluate.return_value = {}
        sample = observer.observe_writer_attempt(page, 'http://127.0.0.1:1', 'pending-then-ready',
                                                   'verified', {'manifest': {}}, wait_timeout_ms=60000)
        page.set_default_timeout.assert_called_once_with(60000)
        self.assertEqual(sample['outcome'], 'timeout')
        self.assertIsNone(sample['elapsed_ms'])

    def test_post_headers_without_consumed_body_cannot_be_classified_as_rejected(self):
        raw = self.raw()
        raw['requests'][0].pop('response_handle')
        raw['requests'][0]['body_ms'] = raw['requests'][0]['parse_ms'] = None
        selected = observer.bridge_observation(raw, {'manifest': {}})['selections'][0]
        self.assertIsNone(selected['post']['accepted'])
        self.assertIsNone(selected['post']['identity_matches'])
        raw['requests'][0]['status'] = 409
        selected = observer.bridge_observation(raw, {'manifest': {}})['selections'][0]
        self.assertIs(selected['post']['accepted'], False)

    def test_invalid_wait_bound_is_retained_without_navigation(self):
        for wait in (True, 0, 9999, 120001, 1.5):
            page = Mock()
            page.evaluate.return_value = {}
            sample = observer.observe_writer_attempt(page, 'http://127.0.0.1:1', 'pending-then-ready',
                                                       'verified', {'manifest': {}}, wait_timeout_ms=wait)
            self.assertEqual(sample['outcome'], 'invalid_response')
            page.goto.assert_not_called()
