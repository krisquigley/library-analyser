"""Additional real packaged-browser latest pending-focus regression."""
import os
import unittest
from tests.acceptance import test_explorer_browser_diagnostic as contracts


@unittest.skipUnless(os.environ.get('RUN_EXPLORER_BROWSER_DIAGNOSTIC') == '1',
                     'explicit real-browser opt-in')
class LatestSelectionAcceptance(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        contracts.RealBrowserDiagnosticAcceptance.setUpClass()

    def test_replaced_pending_selection_focuses_only_latest_and_keeps_real_halo(self):
        assertions = contracts.RealBrowserDiagnosticAcceptance()
        report = assertions.collect('latest-selection')
        sample = report['samples'][0]
        assertions.assert_ready_lifecycle(sample)
        self.assertTrue(sample['selection']['latest_accepted'])
        self.assertEqual(sample['focus']['consumed_count'], 1)
        requests = sample['requests']
        self.assertTrue(any(r['route'] == 'asset' for r in requests), 'include actual packaged asset requests')
        self.assertEqual(sum(r['route'] == '/api/current' for r in requests), 2)
        self.assertEqual(sum(r['route'] == '/api/tracks/<id>' for r in requests), 2)
        self.assertIn('WebGL', sample['webgl_context']['api_version'])
        self.assertIn(sample['webgl_context']['implementation'], ('software-swiftshader', 'software-other', 'unclassified'))
        response = sample['graph_response']
        manifest = report['graph_fixture']
        self.assertEqual(response['content_encoding'], 'gzip')
        self.assertEqual(response['content_length'], manifest['encoded']['body_bytes'])
        self.assertEqual(response['consumed_bytes'], manifest['decoded']['body_bytes'])
        self.assertEqual(response['consumed_sha256'], manifest['decoded']['sha256'])
        self.assertEqual(response['json_counts'], manifest['counts'])
        self.assertEqual(report['succeeded'], 1)
