"""What a playlist preview shows (#138): its response models."""
from dataclasses import dataclass


@dataclass(frozen=True)
class PreviewTrack:
    """A placed track. Energy levels are ranks among the eligible tracks, 0 to 1; None where unknown.
    The duration is the audio file's, in seconds (#257); None where unknown."""
    track_id: str
    title: str
    artist: str
    bpm: float
    key: str | None
    camelot: str | None
    arousal: float | None
    energy_level: float | None
    energy_target: float | None
    duration_seconds: float | None = None


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
