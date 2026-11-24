"""What a tag-write action needs to know about one analysed track (#132), read from the analysis database.

Reading only: the Explorer never writes the analysis database.
"""
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class TaggableTrack:
    track_id: str
    sha256: str
    location: str | None
    detected_bpm: object = None
    tonic: object = None
    scale: object = None
    key_strength: object = None
    manual_bpm: str | None = None
    manual_key: str | None = None


class TaggableTracks(Protocol):
    def read(self, track_id: str) -> TaggableTrack | None:
        """The track, or None when the analysis database has no such track."""
        ...
