"""RED: public server-span publication through the existing HTTP report seam.

Caller-owned request records carry ``server_spans``; the outward publisher must
validate them before redacting identifiers. Spans use one process monotonic
clock, opaque request/thread/span IDs and optional parent_id. Inclusive and
exclusive durations are distinct; union time is never a cross-thread total.
These are synthetic clock contracts, not performance targets or runtime hooks.
"""
import json
import math
import unittest

from tools.explorer_http_report import publish_http_report


class DetailPhaseReportTests(unittest.TestCase):
    def span(self, phase, start, end, *, span_id='root', parent_id=None,
             request_id='request-secret', thread_id='thread-secret',
             clock='monotonic', status='ok'):
        return dict(phase=phase, start_ms=start, end_ms=end, span_id=span_id,
                    parent_id=parent_id, request_id=request_id,
                    thread_id=thread_id, clock=clock, status=status)

    def publish(self, spans, *, outcome='ok', observer_mode='observer_on'):
        # Existing public entry point and valid fixtures: absent instrumentation
        # must fail an assertion, never an import/signature/environment error.
        report = publish_http_report(
            attempts=[dict(profile='warm', outcome=outcome, elapsed_ms=20)],
            requests=[dict(method='GET', url='http://127.0.0.1/api/tracks/public',
                           status=200 if outcome == 'ok' else 500,
                           outcome=outcome, elapsed_ms=20, response_bytes=2,
                           server_spans=spans, observer_mode=observer_mode)])
        self.assertIn('server_observation', report,
                      'Missing public request-local server span attribution')
        return report, report['server_observation']

    def test_nested_spans_not_summed_as_sequential_total(self):
        _, observation = self.publish([
            self.span('validation', 0, 10),
            self.span('validation_schema', 1, 4, span_id='schema', parent_id='root'),
            self.span('validation_evidence', 3, 8,
                      span_id='history', parent_id='root'),
            self.span('mapping', 0, 7, span_id='parallel',
                      request_id='other-request', thread_id='other-thread'),
        ])
        spans = observation['spans']
        root = next(span for span in spans if span['phase'] == 'validation')
        self.assertEqual(root['inclusive_ms'], 10)
        self.assertEqual(root['exclusive_ms'], 3,
                         'Subtract union [1,8], not overlapping child sums')
        parallel = next(span for span in spans if span['phase'] == 'mapping')
        self.assertNotEqual(root['request_id'], parallel['request_id'])
        self.assertNotEqual(root['thread_id'], parallel['thread_id'])
        self.assertIsNone(observation['sequential_total_ms'],
                          'Nested/parallel spans are not additive wall time')
        self.assertEqual(observation['observer_mode'], 'observer_on')
        self.assertEqual(observation['scope'], 'server-process-monotonic')

    def test_missing_phase_is_unavailable_not_zero(self):
        _, observation = self.publish([self.span('membership', 2, 2)])
        phases = observation['phases']
        self.assertEqual(phases['membership']['status'], 'measured')
        self.assertEqual(phases['membership']['duration_ms'], 0)
        for phase in ('selected_sql_execute', 'selected_sql_fetch',
                      'stage_preflight', 'stage_decode', 'mapping',
                      'dto_serialization', 'utf8_encoding', 'socket_write'):
            with self.subTest(phase=phase):
                self.assertEqual(phases[phase]['status'], 'unavailable')
                self.assertIsNone(phases[phase]['duration_ms'])
        _, off = self.publish([], observer_mode='observer_off')
        self.assertEqual(off['observer_mode'], 'observer_off')
        self.assertEqual(off['spans'], [])
        self.assertIsNone(off['sequential_total_ms'])

    def test_invalid_clock_or_nonfinite_duration_is_flagged(self):
        report, observation = self.publish([
            self.span('membership', 3, 2),
            self.span('mapping', 0, math.inf, span_id='infinite'),
            self.span('socket_write', math.nan, 2, span_id='nan'),
            self.span('utf8_encoding', 0, 2, span_id='clock', clock='wall'),
            self.span('stage_decode', True, 2, span_id='boolean'),
        ])
        by_phase = {span['phase']: span for span in observation['spans']}
        for phase in ('membership', 'mapping', 'socket_write', 'stage_decode'):
            self.assertEqual(by_phase[phase]['status'], 'invalid_duration')
            self.assertIsNone(by_phase[phase]['inclusive_ms'])
        self.assertEqual(by_phase['utf8_encoding']['status'], 'invalid_clock')
        self.assertIsNone(by_phase['utf8_encoding']['inclusive_ms'])
        json.dumps(report, allow_nan=False)

    def test_failed_attempts_and_partial_spans_survive_redacted_publication(self):
        completed = self.span('validation_schema', 1, 3, span_id='secret-path')
        partial = self.span('validation_evidence', 3, None,
                            span_id='/private/span', status='failed')
        partial.update(exception='PRIVATE_EXCEPTION /private/audio.flac',
                       sql='SELECT PRIVATE_PAYLOAD', parameters=['PRIVATE_BINDING'],
                       payload='PRIVATE_PAYLOAD', hostname='PRIVATE_HOST')
        unknown = self.span('PRIVATE_PHASE /private/audio', 4, 5,
                            span_id='unknown-secret')
        report, observation = self.publish([completed, partial, unknown], outcome='http_error')
        self.assertEqual(report['attempted'], 1)
        self.assertEqual(report['profiles']['warm']['succeeded'], 0)
        spans = observation['spans']
        self.assertEqual(len(spans), 3)
        self.assertEqual(spans[2]['phase'], 'unknown')
        self.assertEqual(spans[0]['inclusive_ms'], 2)
        self.assertEqual(spans[1]['status'], 'failed')
        self.assertIsNone(spans[1]['inclusive_ms'])
        self.assertIsNone(spans[1]['end_ms'])
        encoded = json.dumps(report, allow_nan=False)
        for secret in ('request-secret', 'thread-secret', 'secret-path', '/private',
                       'PRIVATE_EXCEPTION', 'PRIVATE_PAYLOAD', 'PRIVATE_BINDING',
                       'PRIVATE_HOST', 'PRIVATE_PHASE', 'unknown-secret'):
            self.assertNotIn(secret, encoded)
