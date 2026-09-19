import unittest
from music_analyzer.infrastructure.analysis.fingerprint import recipe_fingerprint


class FingerprintTests(unittest.TestCase):
    def test_every_analysis_detail_invalidates_recipe(self):
        baseline = dict(models={'model': 'abc'}, manifest={'metadata': 'one'}, engine='v1',
                        decoder='ffmpeg1', preprocessing='mono-v1', algorithm='stages-v1', max_duration=900)
        expected = recipe_fingerprint(**baseline)
        for key, value in [('models', {'model': 'def'}), ('manifest', {'metadata': 'two'}),
                           ('engine', 'v2'), ('decoder', 'ffmpeg2'), ('preprocessing', 'mono-v2'),
                           ('algorithm', 'stages-v2'), ('max_duration', 800)]:
            self.assertNotEqual(expected, recipe_fingerprint(**{**baseline, key: value}))
        self.assertEqual(expected, recipe_fingerprint(**baseline))
