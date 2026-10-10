"""Supplied overlap operands must remain inside the safe IEEE754 magnitude."""
from copy import deepcopy
from fractions import Fraction
import itertools
import json
import unittest

from tools.explorer_browser_report import publish_browser_report


class BrowserSafeNumericReport(unittest.TestCase):
    @staticmethod
    def sample(task, start=0, end=2, status='observed'):
        return {'outcome': 'timeout', 'elapsed_ms': 12,
                'milestones_ms': {'graph_model_start': start, 'graph_model_end': end},
                'responsiveness': {'long_tasks_status': status, 'long_tasks': [task]}}

    def assert_unsafe_mixed_span_unavailable(self, duration):
        start = 2**53 + 3
        end = float(start)
        self.assertEqual(Fraction(end) - start, 1)
        self.assertEqual(end - start, 0.0)
        sample = self.sample({'start_ms': start, 'end_ms': end,
                              'duration_ms': duration}, start, end)
        original = deepcopy(sample)
        published = publish_browser_report(attempts=[sample])['samples'][0]
        response = published['responsiveness']
        self.assertEqual(response['long_tasks'], [
            {'start_ms': None, 'end_ms': None, 'duration_ms': duration}])
        self.assertIsNone(response['phase_task_overlap_ms'][0]['model'])
        self.assertEqual(published['outcome'], 'timeout')
        self.assertEqual(published['elapsed_ms'], 12)
        self.assertEqual(response['long_tasks_status'], 'observed')
        self.assertEqual(sample, original)
        json.dumps(published, allow_nan=False)

    def test_unsafe_mixed_inconsistent_zero_is_unavailable_not_zero(self):
        self.assert_unsafe_mixed_span_unavailable(0)

    def test_unsafe_mixed_truthful_one_is_explicitly_unavailable(self):
        self.assert_unsafe_mixed_span_unavailable(1)

    def test_safe_finite_mixed_controls_preserve_values_and_overlap(self):
        maximum = 2**53 - 1
        for start, end, duration in ((0, 1.5, 1.5), (0.5, 2, 1.5),
                                     (maximum - 1, float(maximum), 1),
                                     (float(maximum - 1), maximum, 1.0),
                                     (0, maximum, float(maximum))):
            with self.subTest(start=start, end=end, duration=duration):
                task = {'start_ms': start, 'end_ms': end, 'duration_ms': duration}
                response = publish_browser_report(attempts=[
                    self.sample(task, start, end)])['samples'][0]['responsiveness']
                self.assertEqual(response['long_tasks'], [task])
                for key, value in task.items():
                    self.assertIs(type(response['long_tasks'][0][key]), type(value))
                self.assertEqual(response['phase_task_overlap_ms'][0]['model'], duration)

    def test_out_of_range_task_operands_are_null_without_losing_valid_neighbors(self):
        valid = {'start_ms': 0, 'end_ms': 2.0, 'duration_ms': 2}
        values = (2**53, float(2**53), 2**53 + 3, 1e100, 10**309,
                  -(2**53), float('inf'), float('nan'), True)
        for status, field, value in itertools.product(
                ('observed', 'unavailable'), valid, values):
            with self.subTest(status=status, field=field, value=value):
                sample = self.sample(dict(valid, **{field: value}), status=status)
                sample['responsiveness']['long_tasks'].append(valid)
                response = publish_browser_report(attempts=[sample])['samples'][0]['responsiveness']
                self.assertIsNone(response['long_tasks'][0][field])
                self.assertTrue(all(overlap is None for overlap in
                                    response['phase_task_overlap_ms'][0].values()))
                self.assertEqual(response['long_tasks'][1], valid)
                self.assertEqual(response['phase_task_overlap_ms'][1]['model'], 2)
                self.assertEqual(response['long_tasks_status'], status)
                json.dumps(response, allow_nan=False)

    def test_out_of_range_phase_operands_are_unavailable_not_zero(self):
        task = {'start_ms': 0.0, 'end_ms': 2, 'duration_ms': 2.0}
        for field, value in itertools.product(('start', 'end'),
                (2**53, float(2**53), 2**53 + 3, 1e100, 10**309)):
            with self.subTest(field=field, value=value):
                bounds = {'start': 0, 'end': 2}
                bounds[field] = value
                response = publish_browser_report(attempts=[self.sample(
                    task, **bounds)])['samples'][0]['responsiveness']
                self.assertEqual(response['long_tasks'], [task])
                self.assertIsNone(response['phase_task_overlap_ms'][0]['model'])


if __name__ == '__main__':
    unittest.main()
