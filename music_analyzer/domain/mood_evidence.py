"""Which model evidence the mood axis and the Mixxx mood colours can use (#123, #134).

Arousal and valence are native coordinates of one emomusic model, and mood scores are sigmoid outputs of
one Jamendo mood/theme model; evidence from any other model is on a different scale and is never mixed in.
"""
AROUSAL_VALENCE_MODEL = 'emomusic-msd-musicnn-2'
MOOD_THEME_MODEL = 'mtg_jamendo_moodtheme-discogs-effnet-1'


def has_provenance_model(provenance, model_id) -> bool:
    explicit_models = [value for key, value in provenance if key == 'model']
    if explicit_models:
        return all(value == model_id for value in explicit_models)
    return any(key == model_id for key, _value in provenance)
