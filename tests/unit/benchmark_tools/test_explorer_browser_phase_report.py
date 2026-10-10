"""Publication contracts: supplied telemetry is not causal performance evidence."""
import json
from pathlib import Path
import unittest

from tools.explorer_browser_report import publish_browser_report


class BrowserPhaseReport(unittest.TestCase):
    def test_lifecycle_success_does_not_manufacture_contention_observation(self):
        sample = {'outcome': 'ok', 'elapsed_ms': 12, 'contention_status': 'unavailable'}
        published = publish_browser_report(attempts=[sample])['samples'][0]
        self.assertEqual(published['outcome'], 'ok')
        self.assertEqual(published.get('contention_status'), 'unavailable')
        sample['contention_status'] = '/private/secret'
        published = publish_browser_report(attempts=[sample])['samples'][0]
        self.assertEqual(published.get('contention_status'), 'unknown')

    def test_invalid_frame_chronology_retains_attempt_and_receipt_not_success(self):
        sample = {'input_observations': [{'attempt_ms': 900, 'received_ms': 30,
                                         'frame_ms': 20, 'is_trusted': True, 'outcome': 'ok'}]}
        record = publish_browser_report(attempts=[sample])['samples'][0]['input_observations'][0]
        self.assertEqual(record['attempt_ms'], 900)
        self.assertEqual(record['received_ms'], 30)
        self.assertIsNone(record['frame_ms'])
        self.assertEqual(record['outcome'], 'invalid_response')

    def test_timeout_without_receipt_cannot_claim_trusted_input(self):
        sample = {'input_observations': [{'attempt_ms': 900, 'received_ms': None,
                                         'frame_ms': 20, 'is_trusted': True, 'outcome': 'timeout'}]}
        record = publish_browser_report(attempts=[sample])['samples'][0]['input_observations'][0]
        self.assertEqual(record['attempt_ms'], 900)
        self.assertIsNone(record['frame_ms'])
        self.assertIsNone(record['is_trusted'])
        self.assertEqual(record['outcome'], 'timeout')

    def test_incomplete_receipt_outcome_remains_unavailable(self):
        sample = {'input_observations': [{'outcome': 'unavailable'}]}
        record = publish_browser_report(attempts=[sample])['samples'][0]['input_observations'][0]
        self.assertEqual(record['outcome'], 'unavailable')
        self.assertIsNone(record['received_ms'])
        self.assertIsNone(record['frame_ms'])

    def test_input_attempt_timeout_preserves_separate_clocks_and_null_receipt(self):
        sample = {'outcome': 'timeout', 'input_observations': [{
            'action': 'input', 'attempt_clock': 'host-monotonic', 'attempt_ms': 900,
            'phase_at_attempt': 'body', 'receipt_clock': 'browser-performance',
            'received_ms': None, 'frame_ms': None, 'is_trusted': None,
            'phase_at_receipt': 'pending', 'outcome': 'timeout',
            'attempt_to_receipt_ms': 800, 'private': '/home/private'}]}
        published = publish_browser_report(attempts=[sample])['samples'][0]
        self.assertEqual(published.get('input_observations'), [{
            'action': 'input', 'attempt_clock': 'host-monotonic', 'attempt_ms': 900,
            'phase_at_attempt': 'body', 'receipt_clock': 'browser-performance',
            'received_ms': None, 'frame_ms': None, 'is_trusted': None,
            'phase_at_receipt': 'pending', 'outcome': 'timeout'}])

    def test_input_observation_labels_and_nonfinite_fields_are_redacted(self):
        sample = {'input_observations': [{'action': '/private/selection',
            'attempt_clock': 'private-clock', 'attempt_ms': float('inf'),
            'received_ms': -1, 'frame_ms': True, 'is_trusted': 'yes',
            'phase_at_attempt': '/private', 'phase_at_receipt': '/private',
            'outcome': 'secret', 'receipt_clock': 'browser-performance'}]}
        record = publish_browser_report(attempts=[sample])['samples'][0].get('input_observations')
        self.assertIsNotNone(record)
        self.assertEqual(record[0]['action'], 'unknown')
        for key in ('attempt_ms', 'received_ms', 'frame_ms', 'is_trusted'):
            self.assertIsNone(record[0][key])
        self.assertNotIn('private', json.dumps(record, allow_nan=False))

    def test_docs_explain_observer_modes_and_noncausal_clocks(self):
        text = (Path(__file__).resolve().parents[3] / 'docs/explorer-browser-diagnostic.md').read_text()
        for phrase in ('native-json', 'consumed identity unavailable', 'overlap is not causation',
                       'host monotonic', 'trusted', 'presentation proxy', '5/20'):
            self.assertIn(phrase, text)

    def test_native_mode_cannot_publish_a_consumed_hash(self):
        sample = {'outcome': 'timeout', 'observer_mode': 'native-json',
                  'graph_response': {'consumed_bytes': 12, 'consumed_sha256': 'a' * 64,
                                     'consumed_identity_status': 'verified'}}
        published = publish_browser_report(attempts=[sample])['samples'][0]
        self.assertEqual(published.get('observer_mode'), 'native-json')
        self.assertEqual(published['graph_response']['consumed_identity_status'],
                         'unavailable-native-json')
        self.assertIsNone(published['graph_response']['consumed_bytes'])
        self.assertIsNone(published['graph_response']['consumed_sha256'])

    def test_cross_phase_task_overlap_is_ambiguous_not_gpu_attribution(self):
        sample = {'outcome': 'timeout', 'milestones_ms': {
            'graph_model_start': 25, 'graph_model_end': 36,
            'graph_scene_start': 36, 'graph_scene_end': 49},
            'responsiveness': {'long_tasks': [{'start_ms': 10, 'end_ms': 70, 'duration_ms': 60}]}}
        published = publish_browser_report(attempts=[sample])['samples'][0]
        self.assertEqual(published.get('responsiveness', {}).get('phase_task_overlap_ms'),
                         [{'model': 11, 'scene': 13, 'json': None, 'verification': None, 'body': None, 'native_json': None}])
        self.assertEqual(published['responsiveness']['attribution'], 'overlap-not-causation')
        self.assertIsNone(published['responsiveness']['gpu_time_ms'])

    def test_inconsistent_task_duration_cannot_generate_plausible_overlap(self):
        sample = {'outcome': 'timeout', 'milestones_ms': {
            'graph_body_start': 10, 'graph_body_end': 20,
            'graph_native_json_start': 10, 'graph_native_json_end': 30},
            'responsiveness': {'long_tasks': [{'start_ms': 10, 'end_ms': 70, 'duration_ms': 1}]}}
        observed = publish_browser_report(attempts=[sample])['samples'][0]['responsiveness']
        self.assertTrue(all(value is None for value in observed['phase_task_overlap_ms'][0].values()))
        sample['responsiveness']['long_tasks'][0]['duration_ms'] = 60
        observed = publish_browser_report(attempts=[sample])['samples'][0]['responsiveness']
        self.assertEqual(observed['phase_task_overlap_ms'][0]['body'], 10)
        self.assertEqual(observed['phase_task_overlap_ms'][0]['native_json'], 20)

    def test_invalid_task_fields_are_null_and_unknown_payloads_never_publish(self):
        sample = {'outcome': 'timeout', 'responsiveness': {'long_tasks': [
            {'start_ms': -1, 'end_ms': float('inf'), 'duration_ms': True,
             'name': '/private/audio.wav'}], 'gpu_time_ms': 12}}
        published = publish_browser_report(attempts=[sample])['samples'][0]
        self.assertEqual(published.get('responsiveness', {}).get('long_tasks'),
                         [{'start_ms': None, 'end_ms': None, 'duration_ms': None}])
        self.assertIsNone(published['responsiveness']['gpu_time_ms'])
        self.assertNotIn('/private', json.dumps(published, allow_nan=False))

    def test_incomplete_or_reversed_phase_is_not_zero_overlap(self):
        sample = {'outcome': 'timeout', 'milestones_ms': {
            'graph_model_start': 40, 'graph_model_end': 30},
            'responsiveness': {'long_tasks': [{'start_ms': 10, 'end_ms': 70, 'duration_ms': 60}]}}
        published = publish_browser_report(attempts=[sample])['samples'][0]
        self.assertEqual(published.get('responsiveness', {}).get('phase_task_overlap_ms'),
                         [{'model': None, 'scene': None, 'json': None, 'verification': None, 'body': None, 'native_json': None}])
