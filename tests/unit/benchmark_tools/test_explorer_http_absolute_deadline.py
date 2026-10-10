"""Finite loopback trickles distinguish absolute deadlines from inactivity limits."""
from contextlib import contextmanager
import socket
import threading
import time
import unittest
from unittest.mock import patch

from tools.explorer_http_diagnostic import _request, _sample, publish_http_report


@contextmanager
def trickle_server(*, status=200, headers=False):
    listener = socket.socket()
    listener.bind(('127.0.0.1', 0))
    listener.listen(1)
    listener.settimeout(1)
    stop = threading.Event()

    def serve():
        try:
            connection, _ = listener.accept()
            with connection:
                connection.settimeout(1)
                connection.recv(65536)
                if headers:
                    chunks = [b'HTTP/1.1 200 OK\r\n'] + [b'X-Trickle: a\r\n'] * 10
                    chunks += [b'Content-Length: 2\r\n\r\n{}']
                else:
                    connection.sendall(('HTTP/1.1 %d Result\r\nContent-Length: 12\r\n\r\n' % status).encode())
                    chunks = [b'{'] + [b' '] * 10 + [b'}']
                for chunk in chunks:
                    if stop.is_set():
                        break
                    connection.sendall(chunk)
                    if stop.wait(.020):
                        break
        except (OSError, TimeoutError):
            pass  # Client deadline closes its socket before the finite stream ends.

    thread = threading.Thread(target=serve)
    thread.start()
    try:
        yield 'http://127.0.0.1:%d' % listener.getsockname()[1]
    finally:
        stop.set()
        listener.close()
        thread.join(2)
        if thread.is_alive():
            raise AssertionError('scratch server failed to stop')


class AbsoluteDeadlineTests(unittest.TestCase):
    def assert_deadline(self, observation):
        self.assertEqual(observation['outcome'], 'timeout')
        self.assertGreaterEqual(observation['elapsed_ms'], 35)
        self.assertLess(observation['elapsed_ms'], 150)

    def test_body_and_http_error_trickles_retain_partial_evidence(self):
        for status in (200, 503):
            with self.subTest(status=status), trickle_server(status=status) as base:
                requests, intervals = [], []
                payload, outcome = _request(base, '/api/state', 'GET', .050,
                                            requests, intervals, 'get_state')
                self.assert_deadline(requests[0])
                self.assertEqual(outcome, 'timeout')
                self.assertIsNone(payload)
                self.assertEqual(requests[0]['status'], status)
                self.assertGreater(requests[0]['response_bytes'], 0)
                self.assertLess(requests[0]['response_bytes'], 12)
                self.assertEqual(len(intervals), 1)

    def test_header_trickle_uses_same_absolute_deadline(self):
        with trickle_server(headers=True) as base:
            requests, intervals = [], []
            _request(base, '/api/state', 'GET', .050, requests, intervals, 'get_state')
            self.assert_deadline(requests[0])
            self.assertEqual(requests[0]['response_bytes'], 0)

    def test_connect_time_is_not_a_fresh_body_budget(self):
        connect = socket.create_connection

        def delayed_connect(*args, **kwargs):
            time.sleep(.035)
            return connect(*args, **kwargs)

        with trickle_server() as base, patch('socket.create_connection', side_effect=delayed_connect):
            requests, intervals = [], []
            _request(base, '/api/state', 'GET', .050, requests, intervals, 'get_state')
            self.assert_deadline(requests[0])
            self.assertEqual(requests[0]['status'], 200)
            self.assertGreater(requests[0]['response_bytes'], 0)
            self.assertLess(requests[0]['response_bytes'], 12)

    def test_failed_trickle_sample_is_not_successful_p95(self):
        with trickle_server() as base:
            requests, intervals = [], []
            attempt = _sample(base, .050, requests, intervals, 1)
        report = publish_http_report(attempts=[attempt], requests=requests, intervals=intervals)
        self.assertEqual(report['profiles']['warm']['failures'], {'timeout': 1})
        self.assertEqual(report['profiles']['warm']['succeeded'], 0)
        self.assertIsNone(report['profiles']['warm']['p95_ms'])
        self.assertEqual(report['samples'][0]['outcome'], 'timeout')


if __name__ == '__main__':
    unittest.main()
