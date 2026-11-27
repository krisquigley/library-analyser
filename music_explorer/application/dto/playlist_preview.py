"""What a playlist preview shows (#138): the response models of a recipe's preview and a hand-built playlist's (#287)."""
from dataclasses import dataclass


@dataclass(frozen=True)
class PreviewTrack:
    """A placed track. Its arousal and the arc's target are raw arousal, as the graph shows it (#265), and its valence
    raw valence (#294); None where unknown. The duration is the audio file's, in seconds (#257); None where unknown."""
    track_id: str
    title: str
    artist: str
    bpm: float
    key: str | None
    camelot: str | None
    arousal: float | None
    energy_target: float | None
    duration_seconds: float | None = None
    valence: float | None = None


@dataclass(frozen=True)
class PreviewTransition:
    """A step between two placed tracks; None where it cannot be told."""
    from_track_id: str
    to_track_id: str
    key_compatible: bool | None
    bpm_step_smooth: bool | None
    bpm_change: float | None


@dataclass(frozen=True)
class PlaylistPreview:
    tracks: tuple[PreviewTrack, ...]
    transitions: tuple[PreviewTransition, ...]
    complete: bool
    warning: str | None
