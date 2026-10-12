"""The stored graph fingerprint contract is nonempty text, not digest syntax."""
import unittest

from music_analyzer.domain.projection import validate_graph_source_fingerprint


class GraphSourceFingerprintTests(unittest.TestCase):
    def test_requires_nonempty_text(self):
        for value in ('', None, False, 0):
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_graph_source_fingerprint(value)

    def test_does_not_invent_digest_or_whitespace_rules(self):
        for value in ('fingerprint', ' ', 'False', '0'):
            with self.subTest(value=value):
                validate_graph_source_fingerprint(value)
