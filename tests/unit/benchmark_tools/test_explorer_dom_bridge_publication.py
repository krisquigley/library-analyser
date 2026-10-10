"""Supplied DOM observations remain sanitized and distinct from request identity."""
import json
import unittest

from tests.acceptance.test_explorer_db_detail_browser_diagnostic import bridge_observation
from tools.explorer_browser_report import publish_browser_report


class DOMBridgePublicationTests(unittest.TestCase):
    def publish(self, presented, identity):
        bridge = bridge_observation()
        bridge['selections'][0].update(detail_presented=presented, dom_identity_matches=identity)
        return publish_browser_report(attempts=[{
            'profile': 'process-cold', 'outcome': 'ok', 'elapsed_ms': 12,
            'detail_bridge': bridge, 'failures': [],
        }])

    def test_structural_presentation_can_succeed_with_unavailable_dom_identity(self):
        report = self.publish(True, None)
        selection = report['samples'][0]['detail_bridge']['selections'][0]
        self.assertIs(selection['detail_presented'], True)
        self.assertIsNone(selection['dom_identity_matches'])
        self.assertIs(selection['detail']['identity_matches'], True)
        self.assertEqual(report['samples'][0]['outcome'], 'ok')

    def test_missing_false_or_malformed_supplied_presentation_is_not_success(self):
        for value in (False, None, 1, 'private DOM text'):
            with self.subTest(value=value):
                report = self.publish(value, None)
                self.assertEqual(report['samples'][0]['outcome'], 'invalid_response')
                self.assertEqual(report['samples'][0]['failures'],
                                 [{'flow': 'lifecycle', 'outcome': 'invalid_response'}])
                selection = report['samples'][0]['detail_bridge']['selections'][0]
                self.assertIs(selection['detail_presented'], False if value is False else None)
                self.assertNotIn('private DOM text', json.dumps(report, allow_nan=False))

    def test_dom_identity_is_a_boolean_or_unavailable_not_request_identity(self):
        for value, expected in ((True, True), (False, False), (None, None),
                                (1, None), ('private DOM text', None)):
            with self.subTest(value=value):
                report = self.publish(True, value)
                selection = report['samples'][0]['detail_bridge']['selections'][0]
                self.assertIs(selection['dom_identity_matches'], expected)
                self.assertEqual(report['samples'][0]['outcome'], 'ok')
                self.assertNotIn('private DOM text', json.dumps(report, allow_nan=False))

    def test_original_supplied_bridge_without_dom_fields_keeps_compatibility(self):
        report = publish_browser_report(attempts=[{
            'profile': 'process-cold', 'outcome': 'ok', 'elapsed_ms': 12,
            'detail_bridge': bridge_observation(),
        }])
        selection = report['samples'][0]['detail_bridge']['selections'][0]
        self.assertNotIn('detail_presented', selection)
        self.assertNotIn('dom_identity_matches', selection)
        self.assertEqual(report['samples'][0]['outcome'], 'ok')
