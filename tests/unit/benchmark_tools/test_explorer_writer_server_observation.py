"""Bounded outward B observation without changing reader policies."""
import unittest
from tools.explorer_writer_server_observation import BoundedWriterServerObservation as ServerObservation


class WriterServerSamplingTests(unittest.TestCase):
    def test_repeated_evidence_spans_are_bounded_and_omitted_failures_counted(self):
        observer = ServerObservation()
        observer.local.context = {'request_id': 'internal', 'spans': [], 'stack': []}
        with observer.span('validation'):
            for index in range(100):
                try:
                    with observer.span('validation_evidence_decode'):
                        if index == 99:
                            raise ValueError('private payload')
                except ValueError:
                    pass
        self.assertLessEqual(len(observer.local.context['spans']), 17)
        counts = observer.local.context['sampling']['validation_evidence_decode']
        self.assertEqual(counts, {'observed': 16, 'omitted': 84, 'omitted_failed': 1})
        self.assertEqual(observer.local.context['stack'], [])
        observer.requests.append(observer.local.context)
        report = observer.sampling_report()
        self.assertEqual(report['status'], 'sampled')
        self.assertEqual(report['phases']['validation_evidence_decode'], counts)
        self.assertNotIn('private payload', str(report))
        self.assertNotIn('internal', str(report))

    def test_selected_operations_and_parent_inclusive_span_are_preserved(self):
        observer = ServerObservation()
        observer.local.context = {'request_id': 'internal', 'spans': [], 'stack': []}
        with observer.span('selected_read'):
            with observer.span('stage_decode'):
                pass
        self.assertEqual([span['phase'] for span in observer.local.context['spans']],
                         ['selected_read', 'stage_decode'])
        self.assertEqual(observer.local.context['spans'][0]['status'], 'ok')
