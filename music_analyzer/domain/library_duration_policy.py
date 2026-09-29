"""Active-library duration eligibility policy.

Pure domain rules only: callers must provide a measured duration from an
approved audio probe. Textual tags are not proof of duration.
"""
from dataclasses import dataclass

from music_analyzer.domain.analysis import finite


ACTIVE_LIBRARY_MAX_DURATION_SECONDS = 1200.0
_MEASURED_DURATION_SOURCES = {'mutagen', 'ffprobe'}


@dataclass(frozen=True)
class DurationVerification:
    seconds: float | None
    source: str


@dataclass(frozen=True)
class ActiveLibraryDurationDecision:
    active: bool
    warning: str | None = None


def active_library_duration_policy(verification: DurationVerification | None) -> ActiveLibraryDurationDecision:
    """Decide whether a track may appear in the ACTIVE library.

    Fail closed unless duration is finite and supplied by a measured mutagen or
    ffprobe probe. Exactly 1200.0 seconds is allowed; values strictly greater
    than 1200.0 seconds are excluded.
    """
    if (verification is None or verification.source not in _MEASURED_DURATION_SOURCES
            or verification.seconds is None or not finite(verification.seconds) or verification.seconds <= 0):
        return ActiveLibraryDurationDecision(
            False,
            'duration unverified; excluded from active library until mutagen/ffprobe verifies duration; rescan audio metadata',
        )
    if verification.seconds > ACTIVE_LIBRARY_MAX_DURATION_SECONDS:
        return ActiveLibraryDurationDecision(
            False,
            f'duration {verification.seconds:.3f}s >{ACTIVE_LIBRARY_MAX_DURATION_SECONDS:.1f}s; '
            'excluded from active library; rescan metadata or choose a shorter file',
        )
    return ActiveLibraryDurationDecision(True)
