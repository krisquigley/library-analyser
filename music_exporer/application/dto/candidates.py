"""Framework-free candidate-selection DTOs for the explorer."""
from dataclasses import dataclass
from typing import Mapping

from music_exporer.domain.candidate_selection import CandidateExplanation, NoMatchDetail
from music_exporer.application.dto.explorer import ExplorerMetadata


@dataclass(frozen=True)
class SelectionControlDto:
    name: str
    mode: str = 'off'
    weight: float = 0.0
    parameters: Mapping[str, object] | None = None
    within: str = 'any'


@dataclass(frozen=True)
class CandidateQuery:
    current_track_id: str
    controls: tuple[SelectionControlDto, ...]
    exclude_track_ids: tuple[str, ...] = ()
    limit: int = 50
    after: str | None = None


@dataclass(frozen=True)
class CandidateSummaryDto:
    track_id: str
    display_label: str
    rank: int
    tier: str
    score: float | None
    supported_weight_mass: float
    missing_weight_mass: float
    requested_weight_mass: float
    explanation: CandidateExplanation


@dataclass(frozen=True)
class CandidateResultDto:
    metadata: ExplorerMetadata
    policy_versions: Mapping[str, str]
    current_track_id: str
    controls_echo: tuple[SelectionControlDto, ...]
    candidates: tuple[CandidateSummaryDto, ...]
    excluded_summary: Mapping[str, int]
    no_match_suggestions: tuple[str, ...]
    no_match_details: tuple[NoMatchDetail, ...] = ()
