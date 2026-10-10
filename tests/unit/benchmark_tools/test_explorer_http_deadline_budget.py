"""Supplemental connection-budget and resource ownership contracts."""
import socket
import time
import unittest
from unittest.mock import patch

from tests.unit.benchmark_tools.test_explorer_http_absolute_deadline import trickle_server
from tools.explorer_http_diagnostic import _request


class DeadlineConnectionBudgetTests(unittest.TestCase):
    def test_expired_connect_budget_cannot_send_request_or_read_body(self):
        connect = socket.create_connection

        def delayed_connect(*args, **kwargs):
            # Simulate scheduling/connection setup finishing past its budget.
            # No request bytes have been sent when this collaborator returns.
            time.sleep(.060)
            return connect(*args, **kwargs)

        with trickle_server() as base, patch('socket.create_connection', side_effect=delayed_connect):
            requests, intervals = [], []
            payload, outcome = _request(base, '/api/state', 'GET', .050,
                                        requests, intervals, 'get_state')
        self.assertEqual(outcome, 'timeout')
        self.assertIsNone(payload)
        self.assertIsNone(requests[0]['status'])
        self.assertEqual(requests[0]['response_bytes'], 0)
        self.assertGreaterEqual(requests[0]['elapsed_ms'], 50)
        self.assertLess(requests[0]['elapsed_ms'], 150)


if __name__ == '__main__':
    unittest.main()
