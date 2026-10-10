"""Malformed synthetic loopback clients do not leak server tracebacks."""
import contextlib
import http.client
import io
import unittest
from urllib.parse import urlsplit
from tools.explorer_browser_routes import public_routes


class LoopbackInputBounds(unittest.TestCase):
    def test_malformed_content_length_and_json_are_sanitized_400(self):
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            with public_routes({'encoded_body': b'public'}, 'pending-then-ready') as (url, _):
                target = urlsplit(url)
                for length, body in [('bad', b'{}'), ('1', b'{')]:
                    connection = http.client.HTTPConnection(target.hostname, target.port, timeout=2)
                    try:
                        connection.request('POST', '/api/current', body, {'Content-Length': length})
                        self.assertEqual(connection.getresponse().status, 400)
                    finally:
                        connection.close()
        self.assertEqual(stderr.getvalue(), '')
