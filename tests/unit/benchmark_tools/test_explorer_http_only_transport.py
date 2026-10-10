"""Loopback HTTP requests must not initialize unrelated HTTPS infrastructure."""
import time
import unittest
from unittest.mock import patch
from urllib.request import HTTPSHandler

from tests.unit.benchmark_tools.test_explorer_http_absolute_deadline import trickle_server
from tools.explorer_http_diagnostic import _request


class HTTPOnlyTransportTests(unittest.TestCase):
    def test_http_request_never_initializes_unused_https_handler(self):
        # Python 3.14's HTTPSHandler constructor eagerly creates a TLS context
        # and loads certificates. No TLS setup belongs in numeric loopback HTTP.
        # Spy at the public constructor boundary, independent of Python version
        # or the host's trust-store size; do not relax the deadline to mask it.
        with trickle_server() as base, patch('urllib.request.HTTPSHandler.__init__',
                                             return_value=None) as initialize_https:
            requests, intervals = [], []
            payload, outcome = _request(base, '/api/state', 'GET', .5,
                                        requests, intervals, 'get_state')
        self.assertEqual(outcome, 'ok')
        self.assertEqual(payload, {})
        self.assertEqual(requests[0]['status'], 200)
        initialize_https.assert_not_called()

    def test_unused_trust_store_cannot_consume_http_trickle_deadline(self):
        initialize = HTTPSHandler.__init__

        def expensive_unused_tls(handler, *args, **kwargs):
            # Model an environment whose CA-loading cost exceeds the deadline.
            # A pure HTTP transport must never invoke this unrelated work.
            time.sleep(.060)
            initialize(handler, *args, **kwargs)

        with trickle_server() as base, patch('urllib.request.HTTPSHandler.__init__',
                                             new=expensive_unused_tls):
            requests, intervals = [], []
            payload, outcome = _request(base, '/api/state', 'GET', .050,
                                        requests, intervals, 'get_state')
        self.assertEqual(outcome, 'timeout')
        self.assertIsNone(payload)
        self.assertEqual(requests[0]['status'], 200)
        self.assertGreater(requests[0]['response_bytes'], 0)
        self.assertLess(requests[0]['elapsed_ms'], 150)


if __name__ == '__main__':
    unittest.main()
