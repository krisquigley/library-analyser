"""Which tag changes one tag-write action proposes (#132).

Each change names the file, the field, the value the file holds now and the value the analysis proposes.
An empty tag is filled; a different existing value is replaced only when the listener chose to replace, and
the change says it replaces. An unknown proposal changes nothing. Two previews of the same files and values
give equal change sets, so an apply can tell when anything moved since the listener approved.
"""
from dataclasses import dataclass

from music_explorer.domain.track_tag_values import bpm_tag_value, key_tag_value

FILL_EMPTY = 'fill-empty'
REPLACE_EXISTING = 'replace-existing'
EXISTING_TAG_POLICIES = (FILL_EMPTY, REPLACE_EXISTING)


@dataclass(frozen=True)
class TagChange:
    location: str
    field: str
    current: str | None
    proposed: str
    replaces: bool


@dataclass(frozen=True)
class TrackTagEvidence:
    """What the analysis knows about one track's tempo and key, and where its file is."""
    location: str
    detected_bpm: object
    tonic: object
    scale: object
    key_strength: object
    manual_bpm: str | None
    manual_key: str | None


def planned_track_changes(evidence: TrackTagEvidence, *, current_bpm, current_key, policy: str,
                          minimum_key_strength: float) -> tuple[TagChange, ...]:
    """The BPM and key changes for one file, in that order; fields with nothing to change are left out."""
    proposed_key = key_tag_value(evidence.tonic, evidence.scale, evidence.key_strength, evidence.manual_key,
                                 minimum_strength=minimum_key_strength)
    changes = (planned_change(evidence.location, 'bpm', current_bpm,
                              bpm_tag_value(evidence.detected_bpm, evidence.manual_bpm), policy),
               planned_change(evidence.location, 'key', current_key, proposed_key, policy))
    return tuple(change for change in changes if change is not None)


def planned_change(location: str, field: str, current, proposed, policy: str) -> TagChange | None:
    if policy not in EXISTING_TAG_POLICIES:
        raise ValueError(f'Unknown existing-tag policy "{policy}": use {FILL_EMPTY} or {REPLACE_EXISTING}')
    if not _present(proposed) or current == proposed:
        return None
    if not _present(current):
        return TagChange(location, field, current, proposed, replaces=False)
    if policy == REPLACE_EXISTING:
        return TagChange(location, field, current, proposed, replaces=True)
    return None


def _present(value) -> bool:
    return isinstance(value, str) and bool(value.strip())
