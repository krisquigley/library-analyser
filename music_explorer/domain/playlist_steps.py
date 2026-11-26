"""How one track steps into the next in a playlist (#138, #287): whether their keys mix and how far the tempo moves.

Each part is None where it cannot be told: a key not known well enough, or a tempo missing.
"""
from dataclasses import dataclass

from music_explorer.domain.harmonic_mixing import keys_compatible


@dataclass(frozen=True)
class PlaylistStep:
    key_compatible: bool | None
    bpm_step_smooth: bool | None
    bpm_change: float | None


def playlist_step(before, after, mixing) -> PlaylistStep:
    """The step from one walk track into the next, judged by the harmonic mixing's tolerances."""
    known_keys = before.key is not None and after.key is not None
    smooth = mixing.bpm_step_smooth(before.bpm, after.bpm)
    return PlaylistStep(key_compatible=keys_compatible(before.key, after.key) if known_keys else None,
                        bpm_step_smooth=smooth, bpm_change=float(after.bpm - before.bpm) if smooth is not None else None)
