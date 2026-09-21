"""Framework-free explorer read DTOs; paths stay behind the repository port."""
from dataclasses import dataclass
from typing import Mapping

from music_analyzer.application.dto.analysis import AnalysisReport


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


@dataclass(frozen=True)
class ExplorerSnapshot:
    metadata: ExplorerMetadata
    tracks: tuple[ExplorerTrackDetail, ...]

    @property
    def snapshot(self):
        return ExplorerReadModel('music-analyzer', self.metadata.schema_version, self.metadata.track_count, self.metadata.read_policy)
