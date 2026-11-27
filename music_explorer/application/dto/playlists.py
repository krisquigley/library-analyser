"""Playlist export DTOs."""
from dataclasses import dataclass

from music_explorer.domain.harmonic_mixing import DEFAULT_MINIMUM_KEY_STRENGTH


@dataclass(frozen=True)
class PlayableTrackCandidate:
    track_id: str
    bpm: float
    path: str
    exists: bool = True
    active: bool = True
    catalogued: bool = True
    title: str = ''
    artist: str = ''
    manual_overrides: tuple[str, ...] = ()
    duration_seconds: float | None = None
    key: str | None = None
    scale: str | None = None
    key_strength: float | None = None


@dataclass(frozen=True)
class PlaylistMoodEvidence:
    """Model-compatible arousal, selected-mood score and valence (#294); None when unusable."""
    arousal: float | None = None
    mood_score: float | None = None
    valence: float | None = None


@dataclass(frozen=True)
class M3UPlaylist:
    content: str
    track_ids: tuple[str, ...]
    warning: str | None = None


@dataclass(frozen=True)
class EnergyArcRequest:
    """One arc of an energy plan, as the listener asked for it.

    Energy low and high are levels on the 0-1 rank scale; None leaves that
    end of the range unset. An arc lasts a number of tracks or of minutes
    (#137); a single arc without either spans the whole playlist.
    """
    shape: str
    energy_low: float | None = None
    energy_high: float | None = None
    tracks: object = None
    minutes: object = None


@dataclass(frozen=True)
class PlaylistRecipe:
    """Everything a playlist is generated from (#135).

    Its length is a number of tracks or a duration in minutes, or, when the
    energy plan's arcs have lengths, their sum. Harmonic mixing is on unless
    turned off; an empty energy plan means no arc.
    """
    start_track_id: str
    bpm_min: object
    bpm_max: object
    length: object = None
    duration_minutes: object = None
    harmonic_mixing: bool = True
    minimum_key_strength: object = DEFAULT_MINIMUM_KEY_STRENGTH
    energy_plan: tuple[EnergyArcRequest, ...] = ()
    mood_hold: str | None = None
