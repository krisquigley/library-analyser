import unittest

from music_analyzer.domain import catalogue


class CatalogueArchitectureTests(unittest.TestCase):
    def test_active_duration_policy_lives_only_in_library_duration_policy(self):
        for duplicate_name in (
            'MAX_ACTIVE_DURATION_SECONDS',
            'duration_exclusion_reason',
            'is_active_duration',
        ):
            with self.subTest(duplicate_name=duplicate_name):
                self.assertFalse(
                    hasattr(catalogue, duplicate_name),
                    f'catalogue must not define {duplicate_name}; use library_duration_policy as the single source of truth',
                )


if __name__ == '__main__':
    unittest.main()
