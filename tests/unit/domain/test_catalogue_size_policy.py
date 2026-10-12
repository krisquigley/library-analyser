"""Whole-byte identity size policy remains independent of storage details."""
import unittest

from music_analyzer.domain.catalogue import FileIdentity, validate_file_size


class CatalogueSizePolicyTests(unittest.TestCase):
    def test_accepts_nonnegative_whole_numeric_sizes_without_coercion(self):
        for size in (0, 123, 123.0, False, True):
            with self.subTest(size=size):
                self.assertIsNone(validate_file_size(size))

    def test_rejects_fractional_negative_nonfinite_and_nonnumeric_sizes(self):
        for size in (0.5, -1, -0.5, float('nan'), float('inf'), float('-inf'), '123', None):
            with self.subTest(size=size):
                with self.assertRaisesRegex(ValueError, 'identity size.*nonnegative integer'):
                    validate_file_size(size)

    def test_identity_construction_remains_compatible_for_writer_validation(self):
        identity = FileIdentity('a' * 64, 0.5)
        self.assertEqual(identity.size, 0.5)
        with self.assertRaises(ValueError):
            validate_file_size(identity.size)


if __name__ == '__main__':
    unittest.main()
