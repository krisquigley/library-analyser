"""Additional publication contracts; no performance assertions."""
import unittest

from tests.unit.benchmark_tools import test_explorer_detail_phase_report as contracts


class DetailPhaseReportExtraTests(unittest.TestCase):
    def publish(self, spans, mode='observer_on'):
        helper = contracts.DetailPhaseReportTests()
        return helper.publish(spans, observer_mode=mode)[1]

    def test_explain_observer_cost_is_separate_fixed_phase(self):
        span = contracts.DetailPhaseReportTests().span
        observation = self.publish([span('observer_explain', 0, 3)])
        self.assertEqual(observation['spans'][0]['phase'], 'observer_explain')
        self.assertEqual(observation['phases']['observer_explain']['duration_ms'], 3)
        self.assertEqual(observation['phases']['selected_sql_execute']['status'], 'unavailable')

    def test_historical_evidence_subphases_have_fixed_public_labels(self):
        span = contracts.DetailPhaseReportTests().span
        names = ('validation_evidence_preflight', 'validation_evidence_fetch',
                 'validation_evidence_decode', 'validation_evidence_payload')
        observation = self.publish([span(name, i, i + 1, span_id=name)
                                    for i, name in enumerate(names)])
        self.assertEqual([s['phase'] for s in observation['spans']], list(names))
        for name in names:
            self.assertEqual(observation['phases'][name]['status'], 'measured')

    def test_partial_completed_interval_is_not_complete_phase_measurement(self):
        span = contracts.DetailPhaseReportTests().span
        observation = self.publish([span('selected_sql_fetch', 0, 3, status='partial')])
        self.assertEqual(observation['spans'][0]['status'], 'partial')
        self.assertEqual(observation['spans'][0]['inclusive_ms'], 3)
        self.assertEqual(observation['phases']['selected_sql_fetch']['status'], 'partial')

    def test_cycle_does_not_manufacture_zero_exclusive_time(self):
        span = contracts.DetailPhaseReportTests().span
        observation = self.publish([
            span('validation', 0, 10, span_id='a', parent_id='b'),
            span('mapping', 0, 10, span_id='b', parent_id='a'),
        ])
        for published in observation['spans']:
            self.assertEqual(published['status'], 'invalid_hierarchy')
            self.assertIsNone(published['exclusive_ms'])
            self.assertIsNone(published['parent_id'])

    def test_request_root_and_socket_scope_are_fixed_public_labels(self):
        span = contracts.DetailPhaseReportTests().span
        write = span('socket_write', 1, 2, span_id='write', parent_id='root')
        write.update(bytes=2, scope='server_socket_write_not_client_receipt')
        observation = self.publish([span('request', 0, 3), write])
        self.assertEqual(observation['spans'][0]['phase'], 'request')
        self.assertEqual(observation['spans'][1]['bytes'], 2)
        self.assertEqual(observation['spans'][1]['scope'], 'server_socket_write_not_client_receipt')

    def test_fully_contained_overlapping_child_never_adds_time(self):
        span = contracts.DetailPhaseReportTests().span
        observation = self.publish([
            span('validation', 0, 10),
            span('mapping', 1, 8, span_id='wide', parent_id='root'),
            span('mapping', 2, 4, span_id='narrow', parent_id='root'),
        ])
        self.assertEqual(observation['spans'][0]['exclusive_ms'], 3)

    def test_cross_thread_children_do_not_reduce_exclusive_time(self):
        span = contracts.DetailPhaseReportTests().span
        observation = self.publish([
            span('validation', 0, 10),
            span('mapping', 2, 5, span_id='child', parent_id='root', thread_id='other'),
        ])
        self.assertEqual(observation['spans'][0]['exclusive_ms'], 10)
        self.assertIsNone(observation['spans'][1]['parent_id'])

    def test_out_of_bounds_child_cannot_claim_exclusive_time(self):
        span = contracts.DetailPhaseReportTests().span
        observation = self.publish([
            span('validation', 0, 10),
            span('mapping', 2, 12, span_id='child', parent_id='root'),
        ])
        self.assertIsNone(observation['spans'][0]['exclusive_ms'])

    def test_reused_ids_are_scoped_to_request_and_thread(self):
        span = contracts.DetailPhaseReportTests().span
        observation = self.publish([
            span('validation', 0, 10),
            span('validation', 20, 30, request_id='other'),
            span('mapping', 21, 24, span_id='child', parent_id='root', request_id='other'),
        ])
        first, second, child = observation['spans']
        self.assertNotEqual(first['span_id'], second['span_id'])
        self.assertEqual(child['parent_id'], second['span_id'])
        self.assertEqual(second['exclusive_ms'], 7)

    def test_observer_off_never_publishes_supplied_spans_as_measurement(self):
        span = contracts.DetailPhaseReportTests().span
        observation = self.publish([span('mapping', 0, 10)], mode='observer_off')
        self.assertEqual(observation['spans'], [])
        self.assertEqual(observation['phases']['mapping']['status'], 'unavailable')
