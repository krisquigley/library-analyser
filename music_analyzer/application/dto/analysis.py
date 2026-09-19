"""Single-track boundaries; audio buffers remain owned by the decoder adapter."""
from dataclasses import dataclass
from music_analyzer.domain.analysis import ScoreSummary, ScoreWindow


class AnalysisError(Exception):
    """Expected actionable decoder, engine or repository failure."""


@dataclass(frozen=True)
class AudioSource:
    location: str


@dataclass(frozen=True)
class DecodedAudio:
    handle: str
    duration: float
    sample_rate: int


@dataclass(frozen=True)
class StageResult:
    stage: str
    provenance: tuple[tuple[str, str], ...]
    uncertainty: str
    values: tuple[tuple[str, str | float], ...] = ()
    windows: tuple[ScoreWindow, ...] = ()
    summary: ScoreSummary | None = None


@dataclass(frozen=True)
class AnalysisReport:
    run_id: str
    status: str
    stages: tuple[StageResult, ...]
    detail: str = ''
