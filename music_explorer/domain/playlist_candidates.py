"""The candidate tracks as the playlist walk sees them (#120, #122, #123).

A manual annotation wins over detection, so the detected value it replaces is
unknown: a manual key leaves no usable key, a manual energy no arousal, and a
manual mood no mood score.
"""
from music_explorer.domain.harmonic_mixing import usable_key
from music_explorer.domain.playlist_walk import WalkTrack


def walk_track(track, harmonic_mixing):
    return WalkTrack(track.track_id, getattr(track, 'artist', '') or '', getattr(track, 'duration_seconds', None),
                     bpm=track.bpm, key=_key(track, harmonic_mixing))


def usable_energy_and_mood(candidates, evidence):
    """Each candidate's arousal and mood score, where detection is not overridden; unknown ones are left out."""
    arousal, mood = {}, {}
    for track_id, track in candidates.items():
        item = evidence.get(track_id)
        overrides = getattr(track, 'manual_overrides', ())
        if item is not None and item.arousal is not None and 'energy' not in overrides:
            arousal[track_id] = item.arousal
        if item is not None and item.mood_score is not None and 'mood' not in overrides:
            mood[track_id] = item.mood_score
    return arousal, mood


def _key(track, harmonic_mixing):
    if harmonic_mixing is None or 'key' in getattr(track, 'manual_overrides', ()):
        return None
    return usable_key(getattr(track, 'key', None), getattr(track, 'scale', None), getattr(track, 'key_strength', None),
                      minimum_strength=harmonic_mixing.minimum_key_strength)
