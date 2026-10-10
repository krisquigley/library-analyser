"""Supplemental bounds tests: reject before injected fixture allocation or I/O."""
import unittest
from unittest.mock import Mock

from tools.explorer_http_diagnostic import run_public_http_diagnostic


class PublicHTTPDiagnosticBoundsTests(unittest.TestCase):
    def test_invalid_fixture_options_never_enter_injected_factory(self):
        invalid_options = (
            {'track_count': True}, {'track_count': 11}, {'track_count': 20001},
            {'track_count': 5000, 'allow_large': False},
            {'seed': True}, {'seed': -1}, {'seed': 2 ** 32},
            {'history_count': True}, {'history_count': 0}, {'history_count': 4},
            {'allow_large': 1},
        )
        for options in invalid_options:
            with self.subTest(options=options):
                factory = Mock(side_effect=AssertionError('fixture must not allocate'))
                server = Mock(side_effect=AssertionError('server must not start'))
                with self.assertRaises(ValueError):
                    run_public_http_diagnostic(fixture_factory=factory,
                                               server_factory=server, **options)
                factory.assert_not_called()
                server.assert_not_called()

    def test_arbitrarily_large_integer_timeout_rejected_with_value_error_before_io(self):
        factory = Mock(side_effect=AssertionError('fixture must not allocate'))
        server = Mock(side_effect=AssertionError('server must not start'))
        with self.assertRaises(ValueError):
            run_public_http_diagnostic(timeout_seconds=10 ** 1000,
                                       fixture_factory=factory, server_factory=server)
        factory.assert_not_called()
        server.assert_not_called()


if __name__ == '__main__':
    unittest.main()
