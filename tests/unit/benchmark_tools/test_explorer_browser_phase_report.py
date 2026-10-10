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

    @staticmethod
    def trusted_record(action):
        return {'action': action, 'receipt_clock': 'browser-performance',
                'received_ms': 30, 'frame_ms': 40, 'is_trusted': True, 'outcome': 'ok'}

    def test_supplied_success_requires_distinct_sanitized_trusted_action_pairs(self):
        valid = [self.trusted_record(action) for action in ('input', 'selection')]
        cases = [[], valid[:1], [valid[0], valid[0]], None, '/private/raw',
                 [None, valid[1]]]
        for field, value in (('action', '/private/action'), ('is_trusted', False),
                             ('is_trusted', 'true'), ('frame_ms', None),
                             ('frame_ms', float('inf')), ('frame_ms', True),
                             ('frame_ms', 20), ('received_ms', None),
                             ('received_ms', float('nan')), ('received_ms', -1),
                             ('receipt_clock', '/private/clock'), ('outcome', 'timeout')):
            cases.append([dict(valid[0], **{field: value}), valid[1]])
        for records in cases:
            with self.subTest(records=records):
                sample = {'contention_status': 'observed-trusted-input',
                          'input_observations': records}
                published = publish_browser_report(attempts=[sample])['samples'][0]
                self.assertIn(published['contention_status'], ('unavailable', 'invalid_response'))
                self.assertNotIn('/private', json.dumps(published, allow_nan=False))
        published = publish_browser_report(attempts=[{
            'contention_status': 'observed-trusted-input'}])['samples'][0]
        self.assertEqual(published['contention_status'], 'unavailable')

    def test_sanitized_records_cannot_retain_ok_without_trusted_ordered_pair(self):
        for field, value in (('action', '/private/action'), ('is_trusted', False),
                             ('is_trusted', None), ('frame_ms', None),
                             ('frame_ms', float('inf')), ('frame_ms', True),
                             ('receipt_clock', '/private/clock')):
            with self.subTest(field=field, value=value):
                record = dict(self.trusted_record('input'), **{field: value})
                published = publish_browser_report(attempts=[{
                    'input_observations': [record]}])['samples'][0]['input_observations'][0]
                self.assertIn(published['outcome'], ('unavailable', 'invalid_response'))

    def test_valid_pairs_preserve_success_but_never_upgrade_explicit_failure(self):
        records = [self.trusted_record(action) for action in ('selection', 'input')]
        for status in ('observed-trusted-input', 'unavailable', 'invalid_response'):
            published = publish_browser_report(attempts=[{
                'contention_status': status, 'input_observations': records}])['samples'][0]
            self.assertEqual(published['contention_status'], status)
            self.assertEqual([r['outcome'] for r in published['input_observations']], ['ok', 'ok'])
        for outcome in ('timeout', 'unavailable', 'invalid_response'):
            failed = [dict(records[0], outcome=outcome), records[1]]
            published = publish_browser_report(attempts=[{
                'contention_status': 'observed-trusted-input',
                'input_observations': failed}])['samples'][0]
            self.assertNotEqual(published['contention_status'], 'observed-trusted-input')
            self.assertEqual(published['input_observations'][0]['outcome'], outcome)

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

    def test_empty_long_tasks_preserve_observed_and_unavailable_status(self):
        published = []
        for status in ('observed', 'unavailable'):
            with self.subTest(status=status):
                sample = {'responsiveness': {'long_tasks': [], 'long_tasks_status': status}}
                response = publish_browser_report(attempts=[sample])['samples'][0]['responsiveness']
                published.append(response)
                self.assertEqual(response.get('long_tasks_status'), status)
                self.assertEqual(response['long_tasks'], [])
        self.assertEqual({key: value for key, value in published[0].items()
                          if key != 'long_tasks_status'},
                         {key: value for key, value in published[1].items()
                          if key != 'long_tasks_status'})

    def test_absent_or_invalid_long_tasks_status_defaults_to_unavailable(self):
        sources = [{'long_tasks': []}]
        for status in (None, '', 'unknown', 'Observed', '/private/raw-status',
                       True, 1, [], {}, float('nan')):
            sources.append({'long_tasks': [], 'long_tasks_status': status})
        sources.extend((None, [], '/private/raw-responsiveness'))
        for source in sources:
            with self.subTest(source=source):
                sample = {'responsiveness': source}
                response = publish_browser_report(attempts=[sample])['samples'][0]['responsiveness']
                self.assertEqual(response.get('long_tasks_status'), 'unavailable')
                self.assertEqual(response['long_tasks'], [])
                self.assertNotIn('/private', json.dumps(response, allow_nan=False))

    def test_huge_task_timing_retains_failed_attempt_with_unavailable_overlap(self):
        sample = {'outcome': 'timeout', 'elapsed_ms': 12, 'milestones_ms': {
            'graph_model_start': 0, 'graph_model_end': 1},
            'responsiveness': {'long_tasks_status': 'observed', 'long_tasks': [
                {'start_ms': 0, 'end_ms': 10**309, 'duration_ms': 10**309}]}}
        report = publish_browser_report(attempts=[sample])
        self.assertEqual(len(report['samples']), 1)
        published = report['samples'][0]
        self.assertEqual(published['outcome'], 'timeout')
        self.assertEqual(published['elapsed_ms'], 12)
        observed = published['responsiveness']
        self.assertEqual(observed['long_tasks_status'], 'observed')
        self.assertEqual(observed['long_tasks'], [
            {'start_ms': 0, 'end_ms': None, 'duration_ms': None}])
        self.assertTrue(all(value is None for value in
                            observed['phase_task_overlap_ms'][0].values()))
        json.dumps(report, allow_nan=False)

    def test_unrepresentable_phase_cannot_abort_valid_float_task_report(self):
        sample = {'outcome': 'timeout', 'milestones_ms': {
            'graph_model_start': 10**309, 'graph_model_end': 10**309},
            'responsiveness': {'long_tasks_status': 'observed', 'long_tasks': [
                {'start_ms': 0.0, 'end_ms': 1.0, 'duration_ms': 1.0}]}}
        published = publish_browser_report(attempts=[sample])['samples'][0]
        self.assertEqual(published['outcome'], 'timeout')
        self.assertEqual(published['responsiveness']['long_tasks_status'], 'observed')
        self.assertIsNone(published['responsiveness']['phase_task_overlap_ms'][0]['model'])
        json.dumps(published, allow_nan=False)

    def test_invalid_numeric_tasks_preserve_status_identity_and_valid_controls(self):
        valid = {'start_ms': 0, 'end_ms': 2, 'duration_ms': 2}
        for status in ('observed', 'unavailable'):
            for mode in ('verified', 'native-json'):
                for field in valid:
                    for invalid in (-1, float('nan'), float('inf'), -float('inf'),
                                    10**309, -(10**309)):
                        with self.subTest(status=status, mode=mode, field=field,
                                          invalid=invalid):
                            sample = {'outcome': 'timeout', 'elapsed_ms': 12,
                                'observer_mode': mode,
                                'graph_response': {'consumed_identity_status': 'verified',
                                    'consumed_sha256': 'a' * 64, 'consumed_bytes': 12},
                                'contention_status': 'observed-trusted-input',
                                'input_observations': [self.trusted_record(action)
                                    for action in ('input', 'selection')],
                                'milestones_ms': {'graph_model_start': 0,
                                                  'graph_model_end': 1},
                                'responsiveness': {'long_tasks_status': status,
                                    'long_tasks': [dict(valid, **{field: invalid},
                                                        name='/private/task-id'), valid]}}
                            report = publish_browser_report(attempts=[sample])
                            published = report['samples'][0]
                            observed = published['responsiveness']
                            self.assertEqual(published['outcome'], 'timeout')
                            self.assertEqual(observed['long_tasks_status'], status)
                            self.assertIsNone(observed['long_tasks'][0][field])
                            self.assertTrue(all(value is None for value in
                                observed['phase_task_overlap_ms'][0].values()))
                            self.assertEqual(observed['long_tasks'][1], valid)
                            self.assertEqual(observed['phase_task_overlap_ms'][1]['model'], 1)
                            self.assertEqual(published['contention_status'],
                                             'observed-trusted-input')
                            identity = published['graph_response']
                            self.assertEqual(identity['consumed_identity_status'],
                                'verified' if mode == 'verified' else 'unavailable-native-json')
                            self.assertEqual(identity['consumed_sha256'],
                                             'a' * 64 if mode == 'verified' else None)
                            self.assertNotIn('/private', json.dumps(report, allow_nan=False))

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
