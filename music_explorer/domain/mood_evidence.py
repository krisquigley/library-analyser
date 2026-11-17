"""Which model evidence the mood-axis graph and playlists can use (#123).

Arousal and valence are native coordinates of one emomusic model, and mood
scores are sigmoid outputs of one Jamendo mood/theme model; evidence from any
other model is on a different scale and is never mixed in.
"""
from math import isfinite

AROUSAL_VALENCE_MODEL = 'emomusic-msd-musicnn-2'
MOOD_THEME_MODEL = 'mtg_jamendo_moodtheme-discogs-effnet-1'


def has_provenance_model(provenance, model_id):
    explicit_models = [value for key, value in provenance if key == 'model']
    if explicit_models:
        return all(value == model_id for value in explicit_models)
    return any(key == model_id for key, _value in provenance)


def is_mood_score(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and isfinite(value) and 0.0 <= value <= 1.0
