"""Explorer-owned read DTOs for the analyzer catalogue contract."""
from dataclasses import dataclass
from typing import Mapping


@dataclass(frozen=True)
class TrackMetadata:
    common: tuple[tuple[str, str | tuple[str, ...]], ...] = ()
    tags: tuple[tuple[str, tuple[str, ...]], ...] = ()
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class ScoreSummary:
    labels: tuple[str, ...]
    mean: tuple[float, ...]
    minimum: tuple[float, ...]
    maximum: tuple[float, ...]
    coverage: float
    provisional: bool = True
    uncertainty: str = 'Raw scores are not calibrated; unsampled audio may differ.'


@dataclass(frozen=True)
class StageResult:
    stage: str
    provenance: tuple[tuple[str, str], ...]
    uncertainty: str
    values: tuple[tuple[str, str | float], ...] = ()
    windows: tuple[object, ...] = ()
    summary: ScoreSummary | None = None
    raw_predictions: tuple[tuple[tuple[float, ...], ...], ...] = ()


@dataclass(frozen=True)
class AnalysisReport:
    run_id: str
    status: str
    stages: tuple[StageResult, ...]
    detail: str = ''


@dataclass(frozen=True)
class ExplorerReadModel:
    application_name: str
    schema_version: int
    track_count: int
    read_policy: str = 'bounded_read_transaction'


@dataclass(frozen=True)
class ExplorerTrackRecord:
    track_id: str
    sha256: str
    size: int
    locations: tuple[str, ...]
    run: AnalysisReport | None
    overrides: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class ExplorerStoredTrack:
    track_id: str
    sha256: str
    size: int
    display_label: str
    available_locations: int
    run: AnalysisReport | None
    overrides: tuple[tuple[str, str], ...] = ()
    metadata: TrackMetadata = TrackMetadata()


@dataclass(frozen=True)
class ExplorerMetadata:
    application_id: int
    schema_version: int
    read_policy: str
    track_count: int
    feature_contract_version: str = 'summary-derived-v1'


@dataclass(frozen=True)
class AutomaticEvidence:
    values: tuple[tuple[str, str | float], ...] = ()
    summary_values: tuple[tuple[str, float], ...] = ()
    coverage: float | None = None
    provenance: tuple[tuple[str, str], ...] = ()
    uncertainty: str = ''


@dataclass(frozen=True)
class ExplorerFieldEvidence:
    field: str
    automatic: AutomaticEvidence = AutomaticEvidence()
    manual_text: str | None = None
    effective_source: str = 'missing'
    typed_override_status: str = 'absent'
    missing_reason: str = ''

    @property
    def automatic_values(self):
        return self.automatic.values

    @property
    def summary_values(self):
        return self.automatic.summary_values

    @property
    def typed_unresolved(self):
        return self.typed_override_status == 'unresolved'

    @property
    def missing_reasons(self):
        return (self.missing_reason,) if self.missing_reason else ()

    @property
    def coverage(self):
        return self.automatic.coverage

    @property
    def provenance(self):
        return self.automatic.provenance

    @property
    def uncertainty(self):
        return self.automatic.uncertainty


@dataclass(frozen=True)
class ExplorerTrackDetail:
    handle: str
    track_id: str
    sha256: str
    size: int
    display_label: str
    available_locations: int
    latest_run_id: str | None
    latest_run_status: str | None
    latest_run_detail: str
    fields: Mapping[str, ExplorerFieldEvidence]
    reasons: tuple[str, ...]
    metadata: TrackMetadata = TrackMetadata()


@dataclass(frozen=True)
class AxisValue:
    label: str
    raw: float
    normalized: float
    scale: str
    provenance: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class MoodAxisNode:
    track_id: str
    display_label: str
    x: AxisValue
    y: AxisValue
    z: AxisValue
    bpm: float | None
    genres: tuple[tuple[str, float], ...]
    reasons: tuple[str, ...] = ()
    genre_threshold: float = 0.5
    mood_score: AxisValue | None = None


@dataclass(frozen=True)
class UnpositionedTrack:
    track_id: str
    display_label: str
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class MoodAxisEdge:
    a: str
    b: str
    score: float
    explanation: str
    provenance: Mapping[str, str]
    supported_group_count: int


@dataclass(frozen=True)
class MoodAxisGraph:
    metadata: Mapping[str, object]
    selected_mood: str
    available_moods: tuple[str, ...]
    positioned: tuple[MoodAxisNode, ...]
    unpositioned: tuple[UnpositionedTrack, ...]
    edges: tuple[MoodAxisEdge, ...]


@dataclass(frozen=True)
class ExplorerSnapshot:
    metadata: ExplorerMetadata
    tracks: tuple[ExplorerTrackDetail, ...]

    @property
    def snapshot(self):
        return ExplorerReadModel('music-explorer', self.metadata.schema_version, self.metadata.track_count, self.metadata.read_policy)
