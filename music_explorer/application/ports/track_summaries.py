"""Reading a few tracks' summaries by ID (#243), for the labels around a selection in the graph."""
from typing import Protocol

from music_explorer.application.dto.explorer import ExplorerTrackSummary


class TrackSummariesById(Protocol):
    def track_summaries(self, track_ids: tuple[str, ...]) -> tuple[ExplorerTrackSummary, ...]:
        """The active tracks among those named, in any order; unknown or inactive tracks are left out."""
        ...
