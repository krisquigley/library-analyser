"""What carrying a tags-only change over needs from the analysis database (#223)."""
from dataclasses import dataclass
from typing import Protocol

from music_analyzer.domain.track_succession import StreamedTrack, TrackSuccession


@dataclass(frozen=True)
class SuccessionCandidates:
    """Arrivals: available tracks with no analysis or overrides yet. Departures: tracks whose files are gone but
    whose analysis or overrides remain. Both carry their audio-stream identity; neither already took part in a
    succession on that side."""
    arrivals: tuple[StreamedTrack, ...]
    departures: tuple[StreamedTrack, ...]


class TrackSuccessions(Protocol):
    def candidates(self) -> SuccessionCandidates: ...

    def carry_over(self, succession: TrackSuccession) -> bool:
        """Move the predecessor's analysis and overrides to its successor and record the succession, in one
        transaction. False, changing nothing, when the pairing no longer holds."""
        ...
