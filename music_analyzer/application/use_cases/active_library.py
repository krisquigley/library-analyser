"""Application helpers for active-library filtering."""
from __future__ import annotations

from music_analyzer.domain.catalogue import duration_exclusion_reason


TRUSTED_DURATION_SOURCES = {'mutagen', 'ffprobe'}


def active_exclusion_reason(metadata) -> str:
    """Return an actionable active-library exclusion reason, or an empty string."""
    source = getattr(metadata, 'duration_source', '')
    if source and source not in TRUSTED_DURATION_SOURCES:
        return 'Duration unknown; rescan with a readable measured audio duration before active-library use'
    return duration_exclusion_reason(getattr(metadata, 'duration_seconds', None))


def is_active_library_track(record) -> bool:
    return active_exclusion_reason(record.metadata) == ''
