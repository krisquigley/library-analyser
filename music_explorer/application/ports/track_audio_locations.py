"""Where a track's audio can be read from (#258), as the analysis database records it. Reading only."""
from typing import Protocol


class TrackAudioLocations(Protocol):
    def first_available_location(self, track_id: str) -> str | None:
        """The track's first available file, or None when it has none (or no such track exists)."""
        ...
