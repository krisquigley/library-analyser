"""Where the Mixxx export writes: a new Mixxx-compatible library file, never an existing one (#133)."""
from typing import Protocol

from music_analyzer.domain.mixxx_library import MixxxTrack


class MixxxLibraryExport(Protocol):
    def occupied(self, destination: str) -> bool: ...

    def create(self, destination: str, tracks: tuple[MixxxTrack, ...]) -> None: ...
