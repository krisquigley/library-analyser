"""Exact-file identity and active-library eligibility policy."""
from dataclasses import dataclass
from math import isfinite

MAX_ACTIVE_DURATION_SECONDS = 1200.0


def duration_exclusion_reason(duration_seconds: float | None) -> str:
    if duration_seconds is None:
        return 'Duration unknown; rescan with a readable measured audio duration before active-library use'
    if not isinstance(duration_seconds, (int, float)) or isinstance(duration_seconds, bool) or not isfinite(duration_seconds) or duration_seconds < 0:
        return 'Duration unreadable; rescan with a readable measured audio duration before active-library use'
    if float(duration_seconds) > MAX_ACTIVE_DURATION_SECONDS:
        return f'Duration {float(duration_seconds):.3f}s exceeds active-library limit of {MAX_ACTIVE_DURATION_SECONDS:.1f}s'
    return ''


def is_active_duration(duration_seconds: float | None) -> bool:
    return duration_exclusion_reason(duration_seconds) == ''


@dataclass(frozen=True)
class FileIdentity:
    sha256: str
    size: int

    def __post_init__(self):
        if len(self.sha256) != 64 or any(c not in '0123456789abcdef' for c in self.sha256) or self.size < 0:
            raise ValueError('Identity requires a lowercase SHA-256 digest and nonnegative size')

    @property
    def track_id(self) -> str:
        return f'sha256:{self.sha256}'
