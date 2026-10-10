"""Public HTTP publication contracts, not latency budgets or browser evidence.

PR4a retains caller-owned/raw observations. PR4c must publish a loss-aware,
strict-JSON report through an outward tool without weakening those contracts.
"""
import importlib
import importlib.util
import json
import unittest
from copy import deepcopy


class PublicHttpReportTests(unittest.TestCase):
    def tool(self):
        name = 'tools.explorer_http_diagnostic'
        self.assertIsNotNone(
            importlib.util.find_spec(name),
            'PR4c missing public HTTP diagnostic tool; implement the report contract',
        )
        return importlib.import_module(name)

    def publish(self, attempts, intervals=(), requests=()):
        return self.tool().publish_http_report(
            attempts=attempts, intervals=intervals, requests=requests)

    def test_nearest_rank_counts_and_failures_do_not_merge_profiles(self):
        attempts = [dict(profile='warm', outcome='ok', elapsed_ms=n)
                    for n in range(1, 21)]
        attempts += [dict(profile='warm', outcome='timeout', elapsed_ms=999),
                     dict(profile='warm', outcome='http_error', elapsed_ms=2),
                     dict(profile='process-cold', outcome='ok', elapsed_ms=100)]
        report = self.publish(attempts)
        self.assertEqual(report['attempted'], 23)
        self.assertEqual(report['profiles']['warm'], {
            'attempted': 22, 'succeeded': 20,
            'failures': {'timeout': 1, 'http_error': 1},
            'p50_ms': 10, 'p95_ms': 19, 'max_ms': 20,
        })
        self.assertEqual(report['profiles']['process-cold']['p95_ms'], 100)
        self.assertEqual(len(report['samples']), 23)

    def test_empty_and_all_failed_profiles_have_no_invented_percentiles(self):
        self.assertEqual(self.publish([])['profiles'], {})
        report = self.publish([dict(profile='warm', outcome='timeout', elapsed_ms=None)])
        self.assertEqual(report['profiles']['warm'], {
            'attempted': 1, 'succeeded': 0, 'failures': {'timeout': 1},
            'p50_ms': None, 'p95_ms': None, 'max_ms': None,
        })

    def test_invalid_durations_retained_as_failures_in_strict_json(self):
        attempts = [dict(profile='warm', outcome='ok', elapsed_ms=value)
                    for value in (float('nan'), float('inf'), -1, True)]
        report = self.publish(attempts)
        self.assertEqual(report['profiles']['warm']['failures'], {'invalid_duration': 4})
        self.assertEqual(len(report['samples']), 4)
        json.dumps(report, allow_nan=False)
        self.assertTrue(all(sample['outcome'] == 'invalid_duration'
                            for sample in report['samples']))

    def test_publication_allowlists_labels_and_drops_payloads_without_mutating_input(self):
        marker = 'DO-NOT-PUBLISH-private-path-host-handle-token'
        attempts = [dict(profile=marker, outcome=marker, elapsed_ms=5,
                         response_body=marker, exception=marker, db_path=marker,
                         url='http://' + marker + '/api/tracks/' + marker)]
        requests = [dict(method='GET', url='http://' + marker + '/api/tracks/' + marker + '?token=' + marker),
                    dict(method=marker, url='/' + marker)]
        snapshot = deepcopy(attempts)
        report = self.publish(attempts, requests=requests)
        encoded = json.dumps(report, allow_nan=False)
        self.assertNotIn(marker, encoded)
        self.assertEqual(attempts, snapshot)
        self.assertEqual(report['attempted'], 1)
        self.assertEqual(len(report['samples']), 1)
        self.assertEqual(report['profiles']['unknown']['failures'], {'unknown': 1})
        self.assertEqual(report['request_inventory']['requests'], [
            {'method': 'GET', 'route': '/api/tracks/:handle', 'count': 1},
            {'method': 'UNKNOWN', 'route': 'unknown', 'count': 1},
        ])

    def test_intervals_use_clock_and_flow_and_report_order_errors(self):
        intervals = [dict(clock='monotonic', flow='selection', phase='post_current', start_ms=1, end_ms=3),
                     dict(clock='monotonic', flow='selection', phase='get_detail', start_ms=2, end_ms=4),
                     dict(clock='monotonic', flow='search', phase='get_summary', start_ms=0, end_ms=2),
                     dict(clock='monotonic', flow='selection', phase='get_detail', start_ms=8, end_ms=7)]
        report = self.publish([], intervals=intervals)
        self.assertEqual(report['interval_validation'], {
            'valid': False, 'errors': [
                {'index': 1, 'reason': 'out_of_order'},
                {'index': 3, 'reason': 'reversed_interval'},
            ],
        })
        self.assertEqual(len(report['intervals']), 4)

    def test_interval_labels_are_sanitized_without_losing_validation_errors(self):
        marker = 'DO-NOT-PUBLISH-private-clock-flow-phase'
        intervals = [dict(clock=marker, flow=marker, phase=marker,
                          start_ms=float('nan'), end_ms=2, payload=marker)]
        report = self.publish([], intervals=intervals)
        self.assertNotIn(marker, json.dumps(report, allow_nan=False))
        self.assertEqual(report['interval_validation'], {
            'valid': False, 'errors': [{'index': 0, 'reason': 'invalid_boundary'}],
        })
        self.assertEqual(len(report['intervals']), 1)

    def test_report_explicitly_disclaims_browser_and_speed_evidence(self):
        report = self.publish([])
        self.assertEqual(report['scope'], 'public-synthetic-http-only')
        self.assertEqual(report['browser_evidence'], 'not_measured')
        self.assertEqual(report['latency_budget_result'], 'not_asserted')


if __name__ == '__main__':
    unittest.main()
