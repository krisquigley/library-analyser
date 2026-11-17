"""Model evidence the mood-axis graph and playlists can use (#123)."""
import unittest

from music_explorer.domain.mood_evidence import AROUSAL_VALENCE_MODEL, has_provenance_model, is_mood_score


class MoodEvidenceTests(unittest.TestCase):
    def test_provenance_names_the_model_as_a_key_or_an_explicit_model_entry(self):
        self.assertTrue(has_provenance_model(((AROUSAL_VALENCE_MODEL, 'sha'), ('engine', 'Essentia')), AROUSAL_VALENCE_MODEL))
        self.assertTrue(has_provenance_model((('model', AROUSAL_VALENCE_MODEL),), AROUSAL_VALENCE_MODEL))

    def test_any_other_model_is_incompatible(self):
        self.assertFalse(has_provenance_model((('other-model', 'sha'),), AROUSAL_VALENCE_MODEL))
        self.assertFalse(has_provenance_model((('model', AROUSAL_VALENCE_MODEL), ('model', 'other')), AROUSAL_VALENCE_MODEL))
        self.assertFalse(has_provenance_model((), AROUSAL_VALENCE_MODEL))

    def test_mood_scores_are_finite_values_between_0_and_1(self):
        for value, expected in ((0.0, True), (1.0, True), (0.4, True), (1.01, False), (-0.1, False),
                                (float('nan'), False), (True, False), ('0.5', False), (None, False)):
            with self.subTest(value):
                self.assertIs(expected, is_mood_score(value))


if __name__ == '__main__':
    unittest.main()
