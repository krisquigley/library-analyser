"""Which model's evidence the analyzer's mood axis and Mixxx colours can use (#123, #134)."""
import unittest

from music_analyzer.domain.mood_evidence import AROUSAL_VALENCE_MODEL, MOOD_THEME_MODEL, has_provenance_model


class ProvenanceModelTests(unittest.TestCase):
    def test_an_explicit_model_must_be_the_one_named_every_time(self):
        self.assertTrue(has_provenance_model((('engine', 'Essentia'), ('model', AROUSAL_VALENCE_MODEL)),
                                             AROUSAL_VALENCE_MODEL))
        self.assertFalse(has_provenance_model((('model', AROUSAL_VALENCE_MODEL), ('model', 'other')),
                                              AROUSAL_VALENCE_MODEL))
        self.assertFalse(has_provenance_model((('model', MOOD_THEME_MODEL),), AROUSAL_VALENCE_MODEL))

    def test_without_an_explicit_model_the_model_may_be_a_provenance_key(self):
        self.assertTrue(has_provenance_model(((MOOD_THEME_MODEL, 'sha256:abc'),), MOOD_THEME_MODEL))
        self.assertFalse(has_provenance_model((('engine', 'Essentia'),), MOOD_THEME_MODEL))


if __name__ == '__main__':
    unittest.main()
