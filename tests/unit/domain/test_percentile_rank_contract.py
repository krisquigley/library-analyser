"""Issue #134: the analyzer's percentile rule stays the Explorer's (#123), without either package importing the other."""
import random
import unittest

from music_analyzer.domain.percentile_rank import percentile_ranks as analyzer_ranks
from music_explorer.domain.percentile_rank import percentile_ranks as explorer_ranks


class PercentileRankContractTests(unittest.TestCase):
    def test_both_packages_rank_every_population_the_same(self):
        generator = random.Random(134)
        populations = [{'only': 0.3}, {'a': 1.0, 'b': 1.0}]
        for size in (2, 3, 10, 57):
            populations.append({f't{i}': round(generator.uniform(-3, 3), 1) for i in range(size)})
        for population in populations:
            with self.subTest(size=len(population)):
                self.assertEqual(explorer_ranks(population), analyzer_ranks(population))


if __name__ == '__main__':
    unittest.main()
