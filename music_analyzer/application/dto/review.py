"""Persistence-independent review snapshots; absent evidence stays absent."""
from dataclasses import dataclass
from music_analyzer.application.dto.analysis import AnalysisReport
from music_analyzer.application.dto.catalogue import TrackMetadata


@dataclass(frozen=True)
class StoredTrack:
    track_id: str
    sha256: str
    size: int
    locations: tuple[str, ...]
    run: AnalysisReport | None
    overrides: tuple[tuple[str, str], ...] = ()
    metadata: TrackMetadata = TrackMetadata()


@dataclass(frozen=True)
class ReviewReport:
    track: StoredTrack
    effective: tuple[tuple[str, object], ...]
    selections: tuple[tuple[str, tuple[str, ...] | None], ...]
    threshold: float | None
    needs_review: bool
    reasons: tuple[str, ...]
