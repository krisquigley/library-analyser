"""Framework-free readiness results, not serialized payloads."""
from dataclasses import dataclass

from music_analyzer.application.dto.settings import Settings


@dataclass(frozen=True)
class CheckResult:
    name: str
    available: bool
    detail: str
    remediation: str

    def __post_init__(self) -> None:
        if not self.available and not self.remediation.strip():
            raise ValueError('Unavailable checks require actionable remediation.')


@dataclass(frozen=True)
class DoctorReport:
    checks: tuple[CheckResult, ...]
    foundation_ready: bool
    analysis_ready: bool
    remaining_validation: tuple[str, ...]
    settings: Settings | None = None
