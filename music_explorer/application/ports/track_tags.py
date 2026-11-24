"""The tags of one audio file that the Explorer owns and may write (#132): BPM and key only.

An adapter reads the current values and writes new ones, touching nothing else in the file: no other tag,
picture or frame, and never the audio. A file in a format it cannot tag raises TrackTagsError.
"""
from dataclasses import dataclass
from typing import Protocol


class TrackTagsError(Exception):
    """A file's tags cannot be read or written; the message says why, for the per-file report."""


@dataclass(frozen=True)
class OwnedTags:
    bpm: str | None = None
    key: str | None = None


class TrackTags(Protocol):
    def read_owned(self, location: str) -> OwnedTags: ...

    def write_owned(self, location: str, tags: OwnedTags) -> None:
        """Write each field that is not None; leave the others as they are."""
        ...
