"""Keep a track's analysis and overrides when only its tags changed (#223).

After a scan, each new file whose audio matches exactly one departed track continues that track: the
analysis runs, overrides and batch state move to the new file's id, and the succession is recorded. The audio
is the same, so its evidence still describes it. Safe to run again: whatever was carried over is no longer a
candidate.
"""
from dataclasses import dataclass

from music_analyzer.application.ports.event_bus import EventBus
from music_analyzer.application.ports.track_successions import TrackSuccessions
from music_analyzer.domain.track_succession import TrackSuccession, tags_only_successions


@dataclass(frozen=True)
class TrackEvidenceCarriedOver:
    predecessor_id: str
    successor_id: str


class CarryOverTagChanges:
    def __init__(self, successions: TrackSuccessions, events: EventBus):
        self._successions, self._events = successions, events

    def execute(self) -> tuple[TrackSuccession, ...]:
        candidates = self._successions.candidates()
        pairs = tags_only_successions(arrivals=candidates.arrivals, departures=candidates.departures)
        return tuple(succession for succession in pairs if self._carried(succession))

    def _carried(self, succession: TrackSuccession) -> bool:
        if not self._successions.carry_over(succession):
            return False
        self._events.publish(TrackEvidenceCarriedOver(succession.predecessor_id, succession.successor_id))
        return True
