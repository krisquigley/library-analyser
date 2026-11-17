"""Playlist export DTOs."""
from dataclasses import dataclass


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
class M3UPlaylist:
    content: str
    track_ids: tuple[str, ...]
    warning: str | None = None
