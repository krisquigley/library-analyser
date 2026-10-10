"""Supplied focus telemetry is sanitized observation, never useful-scale proof."""
import json
from pathlib import Path
import unittest

from tools.explorer_browser_report import publish_browser_report


class FocusReportTests(unittest.TestCase):
    def test_docs_define_projection_context_and_unassessed_support(self):
        text = (Path(__file__).resolve().parents[3] / 'docs' /
                'explorer-browser-diagnostic.md').read_text()
        for term in ('projected-vertex-bound', 'frustum-not-occlusion',
                     'support_status', 'usefulness_status', 'not exact raster silhouette',
                     'initial-completed-readback', 'warmed same-page',
                     'camera-plane singularity', 'RUN_EXPLORER_FOCUS_BROWSER',
                     'EXPLORER_BROWSER_SUPERVISED', 'EXPLORER_FOCUS_EVIDENCE_DIR'):
            self.assertIn(term, text)

    def sample(self, focus):
        return publish_browser_report(attempts=[{
            'profile': 'process-cold', 'outcome': 'timeout', 'elapsed_ms': None,
            'focus': focus,
            'input_observations': [{'phase_at_receipt': 'focus'}],
        }])['samples'][0]

    def test_retains_numeric_projection_context_and_partial_motion_without_upgrading_failure(self):
        projection = {
            'status': 'observed', 'measurement': 'projected-vertex-bound',
            'support_status': 'unassessed', 'usefulness_status': 'unassessed',
            'viewport': {'width_px': 800, 'height_px': 600, 'aspect': 4 / 3},
            'camera': {'fov_degrees': 60, 'aspect': 4 / 3, 'near': 1, 'far': 100},
            'controls': {'status': 'observed', 'min_distance': 200,
                         'max_distance': 250, 'enabled': True, 'restrictive': True,
                         'min_distance_status': 'observed', 'max_distance_status': 'observed'},
            'mesh': {'diameter_px': 22, 'diameter_viewport_fraction': 22 / 600,
                     'clipping': {'near': False, 'far': False, 'viewport': True,
                                  'behind_camera': False}},
            'halo': {'diameter_px': 30, 'diameter_viewport_fraction': .05},
        }
        motion = {'cancellations': [{'reason': 'user-orbit', 'at_ms': 30,
                                    'clock': 'browser-performance'}]}
        sample = self.sample({'projection': projection,
                              'context': {'measurement': 'frustum-not-occlusion',
                                          'neighbors_observed': 4, 'neighbors_in_frustum': 1},
                              'motion': motion})
        self.assertEqual(sample['outcome'], 'timeout')
        self.assertEqual(sample['input_observations'][0]['phase_at_receipt'], 'focus')
        self.assertEqual(sample['focus']['projection']['mesh']['diameter_px'], 22)
        self.assertEqual(sample['focus']['projection']['controls'], projection['controls'])
        self.assertEqual(sample['focus']['context']['neighbors_in_frustum'], 1)
        self.assertEqual(sample['focus']['motion']['cancellations'], motion['cancellations'])

    def test_drops_private_labels_and_nulls_invalid_numbers_and_booleans(self):
        sample = self.sample({
            'track_id': 'secret', 'payload': 'secret',
            'projection': {'status': 'secret', 'measurement': 'secret',
                           'support_status': 'supported', 'usefulness_status': 'passed',
                           'viewport': {'width_px': float('nan'), 'height_px': -1, 'aspect': True},
                           'mesh': {'diameter_px': float('inf'),
                                    'clipping': {'near': 'secret', 'far': 0}},
                           'controls': {'min_distance': -1, 'enabled': 1, 'restrictive': 'secret'}},
            'context': {'neighbors_observed': True, 'neighbors_in_frustum': -1},
            'motion': {'cancellations': [{'reason': 'secret', 'at_ms': float('inf'),
                                        'clock': 'secret', 'track_id': 'secret'}]},
        })
        self.assertIn('focus', sample)
        focus = sample['focus']
        self.assertNotIn('secret', json.dumps(focus))
        projection = focus['projection']
        self.assertEqual(projection['support_status'], 'unassessed')
        self.assertEqual(projection['usefulness_status'], 'unassessed')
        for value in projection['viewport'].values():
            self.assertIsNone(value)
        self.assertIsNone(projection['mesh']['diameter_px'])
        self.assertIsNone(projection['mesh']['clipping']['near'])
        self.assertIsNone(projection['mesh']['clipping']['far'])
        self.assertIsNone(projection['controls']['enabled'])
        self.assertIsNone(focus['context']['neighbors_observed'])

    def test_focus_host_attempt_phase_survives_on_separate_host_clock(self):
        sample = publish_browser_report(attempts=[{
            'profile': 'process-cold', 'outcome': 'timeout', 'elapsed_ms': None,
            'input_observations': [{
                'action': 'input', 'phase_at_attempt': 'focus',
                'attempt_clock': 'host-monotonic', 'attempt_ms': 5000,
                'phase_at_receipt': 'focus', 'receipt_clock': 'browser-performance',
                'received_ms': 20, 'frame_ms': 21, 'is_trusted': True, 'outcome': 'ok',
            }],
        }])['samples'][0]
        record = sample['input_observations'][0]
        self.assertEqual(record['phase_at_attempt'], 'focus')
        self.assertEqual(record['attempt_clock'], 'host-monotonic')
        self.assertEqual(record['receipt_clock'], 'browser-performance')
        self.assertEqual(record['phase_at_receipt'], 'focus')
        self.assertEqual(record['outcome'], 'ok')
        self.assertEqual(sample['outcome'], 'timeout')

    def test_motion_start_calls_preserve_partial_chronology_not_completion(self):
        sample = self.sample({'motion': {'starts': [
            {'at_ms': 10, 'clock': 'browser-performance', 'active_after': True,
             'track_id': 'secret'},
            {'at_ms': float('nan'), 'clock': 'secret', 'active_after': 'secret'},
        ]}})
        motion = sample['focus']['motion']
        self.assertIn('starts', motion)
        self.assertEqual(motion['starts'][0], {
            'at_ms': 10, 'clock': 'browser-performance', 'active_after': True})
        self.assertIsNone(motion['starts'][1]['at_ms'])
        self.assertIsNone(motion['starts'][1]['active_after'])
        self.assertNotIn('secret', json.dumps(motion))
        self.assertEqual(sample['outcome'], 'timeout')

    def test_unbounded_controls_are_labeled_without_infinite_numeric_publication(self):
        sample = self.sample({'projection': {'controls': {
            'status': 'observed', 'min_distance': 0, 'max_distance': None,
            'min_distance_status': 'observed', 'max_distance_status': 'unbounded',
            'enabled': True, 'restrictive': False,
        }}})
        controls = sample['focus']['projection']['controls']
        self.assertIn('max_distance_status', controls)
        self.assertEqual(controls['max_distance_status'], 'unbounded')
        self.assertEqual(controls['min_distance_status'], 'observed')
        self.assertIsNone(controls['max_distance'])

    def test_trusted_orbit_receipt_retained_without_inventing_contention_success(self):
        sample = publish_browser_report(attempts=[{
            'profile': 'process-cold', 'outcome': 'timeout', 'elapsed_ms': None,
            'contention_status': 'observed-trusted-input',
            'input_observations': [{'action': 'orbit', 'receipt_clock': 'browser-performance',
                                    'phase_at_receipt': 'focus', 'received_ms': 20,
                                    'frame_ms': 21, 'is_trusted': True, 'outcome': 'ok'}],
        }])['samples'][0]
        self.assertEqual(sample['input_observations'][0]['action'], 'orbit')
        self.assertEqual(sample['input_observations'][0]['outcome'], 'ok')
        self.assertNotEqual(sample['contention_status'], 'observed-trusted-input')
        self.assertEqual(sample['outcome'], 'timeout')

    def test_geometry_availability_and_uncertain_cancellation_reasons_survive(self):
        sample = self.sample({
            'projection': {'mesh': {'status': 'unavailable'}, 'halo': {'status': 'observed'}},
            'context': {'status': 'unavailable'},
            'motion': {'cancellations': [
                {'reason': reason, 'at_ms': 20, 'clock': 'browser-performance'}
                for reason in ('new-focus', 'unclassified')]},
        })
        self.assertIn('status', sample['focus']['projection']['mesh'])
        self.assertEqual(sample['focus']['projection']['mesh']['status'], 'unavailable')
        self.assertEqual(sample['focus']['projection']['halo']['status'], 'observed')
        self.assertEqual(sample['focus']['context']['status'], 'unavailable')
        self.assertEqual([event['reason'] for event in sample['focus']['motion']['cancellations']],
                         ['new-focus', 'unclassified'])

    def test_malformed_nested_telemetry_is_unavailable_not_an_exception(self):
        sample = self.sample({'projection': [], 'context': None, 'motion': 'bad'})
        self.assertIn('focus', sample)
        focus = sample['focus']
        self.assertEqual(focus['projection']['status'], 'unavailable')
        self.assertIsNone(focus['projection']['mesh']['diameter_px'])
        self.assertEqual(focus['motion']['cancellations'], [])
