"""Additional red-first report input and sanitization contracts."""
import json
import unittest

from tests.unit.benchmark_tools.test_explorer_interaction_measurement import measurement


class InteractionReportRobustnessTests(unittest.TestCase):
    def test_invalid_success_durations_are_retained_but_not_quantiles(self):
        attempts = [
            {'profile': 'warm', 'outcome': 'ok', 'elapsed_ms': value}
            for value in (float('nan'), float('inf'), -1, None, True, '12')
        ]
        attempts.append({'profile': 'warm', 'outcome': 'ok', 'elapsed_ms': 0})
        report = measurement.summarize_interactions(attempts)
        self.assertEqual(report.get('attempted'), 7)
        self.assertEqual(report['samples'], attempts)
        self.assertEqual(report['profiles']['warm'], {
            'attempted': 7, 'succeeded': 1, 'failures': {'invalid_duration': 6},
            'p50_ms': 0, 'p95_ms': 0, 'max_ms': 0,
        })

    def test_arbitrary_size_integer_durations_remain_finite(self):
        huge = 10 ** 400
        attempts = [{'profile': 'warm', 'outcome': 'ok', 'elapsed_ms': huge}]
        report = measurement.summarize_interactions(attempts)
        self.assertEqual(report['profiles']['warm'], {
            'attempted': 1, 'succeeded': 1, 'failures': {},
            'p50_ms': huge, 'p95_ms': huge, 'max_ms': huge,
        })

    def test_arbitrary_size_integer_phase_boundaries_remain_finite(self):
        huge = 10 ** 400
        report = measurement.validate_phase_intervals([
            {'clock': 'browser', 'flow': 'detail', 'phase': 'request',
             'start_ms': huge, 'end_ms': huge + 1},
            {'clock': 'browser', 'flow': 'detail', 'phase': 'json',
             'start_ms': huge + 1, 'end_ms': huge + 2},
        ])
        self.assertEqual(report, {'valid': True, 'errors': []})

    def test_empty_summary_has_no_invented_profile(self):
        self.assertEqual(measurement.summarize_interactions([]), {
            'attempted': 0, 'samples': [], 'profiles': {},
        })

    def test_unknown_routes_and_methods_never_disclose_input(self):
        requests = [
            {'method': 'SECRET', 'url': 'https://private/secret/path?token=secret'},
            {'method': 'GET', 'url': '/api/tracks/private/extra'},
            {'method': 'get', 'url': '/api/track-summaries?query=secret'},
            {'method': 'GET', 'url': '/api/tracks/summary-secret'},
        ]
        report = measurement.request_inventory(requests)
        self.assertEqual(report.get('requests'), [
            {'method': 'GET', 'route': '/api/track-summaries', 'count': 1},
            {'method': 'GET', 'route': '/api/tracks/:handle', 'count': 1},
            {'method': 'GET', 'route': 'unknown', 'count': 1},
            {'method': 'UNKNOWN', 'route': 'unknown', 'count': 1},
        ])
        for secret in ('secret', 'private', 'SECRET'):
            self.assertNotIn(secret, json.dumps(report))

    def test_bad_phase_fields_produce_indexed_errors_without_payload_leaks(self):
        intervals = [
            {'clock': 'browser', 'flow': 'detail', 'phase': 'private', 'start_ms': True, 'end_ms': 2},
            {'clock': 'browser', 'flow': 'detail', 'phase': 'private', 'start_ms': 0},
        ]
        report = measurement.validate_phase_intervals(intervals)
        self.assertEqual(report.get('valid'), False)
        self.assertEqual([error['index'] for error in report['errors']], [0, 1])
        self.assertNotIn('private', json.dumps(report))

    def test_manifest_rejects_invalid_source_and_non_graph_arrays(self):
        for body, source in ((b'{}', 'browser-only'), (b'{}', 'private'),
                             (b'{"nodes":{},"links":[],"unpositioned":[]}', 'browser-only')):
            with self.subTest(body=body, source=source):
                with self.assertRaises(ValueError):
                    measurement.graph_manifest(body, source=source)
