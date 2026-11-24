"""Which new file continues which departed track after a tags-only change (#223).

A track's id is its whole file's digest, so rewriting a file's tags makes it a new track. When exactly one
new track and exactly one departed track share the audio between their tag blocks, the new one continues
the old: its analysis and the listener's overrides carry over. Anything ambiguous carries nothing over.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass


@dataclass(frozen=True)
class StreamedTrack:
    track_id: str
    audio_sha256: str


@dataclass(frozen=True)
class TrackSuccession:
    predecessor_id: str
    successor_id: str
    audio_sha256: str


def tags_only_successions(*, arrivals, departures) -> tuple[TrackSuccession, ...]:
    """Pair each new track with the departed track holding the same audio, when the pairing is unambiguous."""
    arriving, departed = _by_audio(arrivals), _by_audio(departures)
    successions = []
    for audio in sorted(arriving.keys() & departed.keys()):
        if len(arriving[audio]) == 1 and len(departed[audio]) == 1:
            (successor,), (predecessor,) = arriving[audio], departed[audio]
            if successor != predecessor:
                successions.append(TrackSuccession(predecessor, successor, audio))
    return tuple(successions)


def _by_audio(tracks) -> dict[str, set[str]]:
    grouped = defaultdict(set)
    for track in tracks:
        grouped[track.audio_sha256].add(track.track_id)
    return grouped
