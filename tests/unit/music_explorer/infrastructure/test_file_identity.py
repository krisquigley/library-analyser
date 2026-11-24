"""Issue #132: a file's identity is the SHA-256 of all its bytes, as the analyzer's scan records it."""
import hashlib
import tempfile
import unittest
from pathlib import Path

from music_explorer.infrastructure.file_identity import Sha256FileIdentity


class Sha256FileIdentityTests(unittest.TestCase):
    def test_the_identity_is_the_hex_sha256_of_the_whole_file_or_none_when_unreadable(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'synthetic.mp3'
            path.write_bytes(b'synthetic bytes' * 100_000)
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), Sha256FileIdentity().sha256(str(path)))
            self.assertIsNone(Sha256FileIdentity().sha256(str(Path(temp) / 'missing.mp3')))


if __name__ == '__main__':
    unittest.main()
