"""Conservative context labels, including a proven combined-corner false positive."""
import math
import unittest

from tools.explorer_browser_report import publish_browser_report
from tests.unit.benchmark_tools.test_explorer_focus_projection_observation import _run_readback


class ConservativeContextClassification(unittest.TestCase):
    def test_disjoint_corner_sphere_is_only_potentially_in_frustum(self):
        # For this symmetric camera, the closest point is on the right/top
        # edge: (a*t, b*t, 20-t). Both active constraints meet there.
        a, b = math.tan(math.radians(30)) * 4 / 3, math.tan(math.radians(30))
        t = (a * 17.5 + b * 13.7 + 20) / (a*a + b*b + 1)
        # Positive right/top normal multipliers prove this edge projection is
        # the closest feasible point (not merely an arbitrary edge distance).
        right_multiplier, top_multiplier = 17.5 - a*t, 13.7 - b*t
        self.assertGreater(right_multiplier, 0)
        self.assertGreater(top_multiplier, 0)
        self.assertAlmostEqual(a*right_multiplier + b*top_multiplier, t-20)
        distance = math.dist((17.5, 13.7, 0), (a*t, b*t, 20-t))
        self.assertGreater(distance, 2)
        self.assertAlmostEqual(distance, 2.1925, places=4)
        self.assertGreater(t, 1)
        self.assertLess(t, 100)
        context = _run_readback("addNode('public-00001',17.5,13.7,0);")['sample']['focus']['context']
        # Keep the historical raw counter: changing rejection math is not this fix.
        self.assertEqual(context['neighbors_in_frustum'], 1)
        self.assertEqual(context.get('classification'), 'potentially-in-frustum')
        self.assertEqual(context.get('method'), 'conservative-six-plane-vertex-bound')

    def test_published_legacy_counter_is_explicitly_conservative(self):
        sample = publish_browser_report(attempts=[{
            'profile': 'process-cold', 'outcome': 'timeout', 'elapsed_ms': None,
            'focus': {'context': {'status': 'observed', 'measurement': 'frustum-not-occlusion',
                                  'neighbors_observed': 1, 'neighbors_in_frustum': 1}},
        }])['samples'][0]
        self.assertEqual(sample['outcome'], 'timeout')
        context = sample['focus']['context']
        self.assertEqual(context['neighbors_in_frustum'], 1)
        self.assertEqual(context.get('classification'), 'potentially-in-frustum')
        self.assertEqual(context.get('method'), 'conservative-six-plane-vertex-bound')

    def test_docs_disclose_combined_corner_false_positive(self):
        from pathlib import Path
        text = (Path(__file__).resolve().parents[3] / 'docs' / 'explorer-browser-diagnostic.md').read_text()
        for term in ('potentially-in-frustum', 'conservative-six-plane-vertex-bound',
                     'corner false positive', '17.5', '13.7', '2.1925'):
            self.assertIn(term, text)
