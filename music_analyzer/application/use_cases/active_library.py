"""Application helpers for active-library filtering."""
from __future__ import annotations

from music_analyzer.domain.library_duration_policy import DurationVerification, active_library_duration_policy


def active_exclusion_reason(metadata) -> str:
    """Return an actionable active-library exclusion reason, or an empty string."""
    source = getattr(metadata, 'duration_source', '')
    seconds = getattr(metadata, 'measured_duration_seconds', None)
    if seconds is None:
        seconds = getattr(metadata, 'duration_seconds', None)
    return active_library_duration_policy(DurationVerification(seconds, source) if source else None).warning or ''


def is_active_library_track(record) -> bool:
    return active_exclusion_reason(record.metadata) == ''
