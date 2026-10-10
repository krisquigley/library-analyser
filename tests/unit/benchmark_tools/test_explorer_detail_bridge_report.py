"""Tiny supplied-observation policy tests; not real browser evidence."""
from copy import deepcopy
import json
import unittest

from tests.acceptance.test_explorer_db_detail_browser_diagnostic import bridge_observation, publish


class DetailBridgePublicationTests(unittest.TestCase):
    def test_unknown_strings_and_request_identities_are_not_published(self):
        bridge = bridge_observation()
        bridge['private'] = '/private/catalogue.db'
        bridge['selections'][0]['post']['request_id'] = '/private/track-secret'
        bridge['selections'][0]['detail']['request_id'] = 'other-private-secret'
        bridge['selections'][0]['handle'] = 'track-secret'
        report = publish(bridge)
        encoded = json.dumps(report, allow_nan=False)
        self.assertNotIn('private', encoded)
        self.assertNotIn('track-secret', encoded)
        self.assertEqual(report['profiles']['process-cold']['succeeded'], 1)
        self.assertIn('detail_bridge', report['samples'][0])
        self.assertEqual(report['samples'][0]['detail_bridge']['selections'][0]['post']['request_id'], 'request-1')

    def test_malformed_success_is_retained_as_failure(self):
        for field, value in [('selections', None), ('latest_selection_sequence', True),
                             ('database_unchanged', False), ('initial_summary_requests', True)]:
            with self.subTest(field=field):
                bridge = bridge_observation()
                bridge[field] = value
                # Explicit elapsed avoids the supplied scaffold assuming well-formed selections.
                from tools.explorer_browser_report import publish_browser_report
                report = publish_browser_report(attempts=[{'profile': 'warm', 'outcome': 'ok', 'elapsed_ms': 12, 'detail_bridge': bridge}])
                self.assertEqual(report['attempted'], 1)
                self.assertEqual(report['profiles']['warm']['succeeded'], 0)
                json.dumps(report, allow_nan=False)

    def test_duplicate_identity_or_invalid_clock_chronology_is_not_success(self):
        for mutate in [lambda s: s['detail'].update(request_id=s['post']['request_id']),
                       lambda s: s.update(clock='host-monotonic'),
                       lambda s: s['post'].update(body_ms=float('nan')),
                       lambda s: s.update(detail_next_frame_ms=14)]:
            bridge = deepcopy(bridge_observation())
            mutate(bridge['selections'][0])
            self.assertEqual(publish(bridge)['profiles']['process-cold']['succeeded'], 0)

    def test_consumed_graph_identity_is_validated_not_copied(self):
        bridge = bridge_observation()
        bridge['graph_consumed'] = {'body_bytes': 123, 'sha256': 'a' * 64,
                                    'private_path': '/private/db'}
        bridge['selections'][0]['is_trusted'] = True
        report = publish(bridge)
        self.assertIn('graph_consumed', report['samples'][0]['detail_bridge'])
        self.assertEqual(report['samples'][0]['detail_bridge']['graph_consumed'],
                         {'sha256': 'a' * 64, 'body_bytes': 123})
        bridge['graph_consumed']['sha256'] = '/private/db'
        self.assertIsNone(publish(bridge)['samples'][0]['detail_bridge']['graph_consumed']['sha256'])
        self.assertEqual(publish(bridge)['profiles']['process-cold']['succeeded'], 0)
        bridge['graph_consumed']['sha256'] = 'a' * 64
        bridge['selections'][0]['is_trusted'] = False
        self.assertEqual(publish(bridge)['profiles']['process-cold']['succeeded'], 0)

    def test_only_observed_bounded_graph_failure_retry_allows_second_request(self):
        bridge = bridge_observation()
        bridge.update(graph_requests=2, graph_retry_count=1,
                      graph_attempt_outcomes=['http_error', 'ok'])
        self.assertEqual(publish(bridge)['profiles']['process-cold']['succeeded'], 1)
        self.assertEqual(publish(bridge)['samples'][0]['detail_bridge']['graph_attempt_outcomes'], ['http_error', 'ok'])
        for outcomes in (None, ['ok', 'ok'], ['http_error', '/private/error']):
            bridge['graph_attempt_outcomes'] = outcomes
            self.assertEqual(publish(bridge)['profiles']['process-cold']['succeeded'], 0)
        bridge.update(graph_requests=3, graph_retry_count=2,
                      graph_attempt_outcomes=['http_error', 'http_error', 'ok'])
        self.assertEqual(publish(bridge)['profiles']['process-cold']['succeeded'], 0)

    def test_owned_metadata_and_request_inventory_are_redacted(self):
        from tools.explorer_browser_report import publish_browser_report
        report = publish_browser_report(attempts=[{'profile': 'warm', 'outcome': 'timeout',
            'requests': [{'method': 'GET', 'route': '/api/mood-axis-graph', 'status': 200},
                         {'method': 'GET', 'route': '/private/database', 'url': 'http://private/db'}],
            'webgl_context': {'api_version': 'webgl2', 'vendor': 'private vendor',
                'renderer': 'WebKit WebGL', 'implementation': 'software-swiftshader'},
            'fault_injection': True, 'graph_fault_injected': True, 'failures': [{'flow': 'graph', 'outcome': 'http_error', 'message': '/private/error'}]}])
        sample = report['samples'][0]
        self.assertIn('requests', sample)
        self.assertEqual(sample['requests'][0]['route'], '/api/mood-axis-graph')
        self.assertEqual(sample['webgl_context']['vendor'], 'unknown')
        self.assertTrue(sample['fault_injection'])
        self.assertIn('graph_fault_injected', sample)
        self.assertTrue(sample['graph_fault_injected'])
        self.assertNotIn('private', json.dumps(report))

    def test_fixture_bounds_and_semantic_match_guard_success(self):
        for field, value in [('track_count', 20001), ('seed', 2**32 + 1), ('history_count', 0)]:
            bridge = bridge_observation()
            bridge['fixture'][field] = value
            self.assertEqual(publish(bridge)['profiles']['process-cold']['succeeded'], 0)
        bridge = bridge_observation()
        bridge['graph_matches_fixture'] = False
        self.assertEqual(publish(bridge)['profiles']['process-cold']['succeeded'], 0)

    def test_success_elapsed_must_match_browser_receipt_to_frame(self):
        from tools.explorer_browser_report import publish_browser_report
        report = publish_browser_report(attempts=[{'profile': 'warm', 'outcome': 'ok',
            'elapsed_ms': 999, 'detail_bridge': bridge_observation()}])
        self.assertEqual(report['profiles']['warm']['succeeded'], 0)
        self.assertEqual(report['attempted'], 1)

    def test_latest_sequence_and_cleanup_require_real_boolean_evidence(self):
        for key, value in [('latest_selection_sequence', 2), ('cleanup', {'browser_closed': 1, 'server_closed': True, 'scratch_removed': True})]:
            bridge = bridge_observation()
            bridge[key] = value
            self.assertEqual(publish(bridge)['profiles']['process-cold']['succeeded'], 0)
