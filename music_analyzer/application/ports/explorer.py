"""Read-only explorer catalogue boundary."""
from typing import Protocol

from music_analyzer.application.dto.explorer import ExplorerStoredTrack


class ExplorerRepository(Protocol):
    def metadata(self) -> dict[str, object]: ...
    def track_ids(self) -> tuple[str, ...]: ...
    def read_track(self, track_id: str) -> ExplorerStoredTrack: ...
