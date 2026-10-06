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


@dataclass(frozen=True)
class M3UPlaylist:
    content: str
    track_ids: tuple[str, ...]
    warning: str | None = None
