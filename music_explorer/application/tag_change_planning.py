"""The change set of a tag-write action (#132), planned from the analysis and the files' current tags.

Previewing and applying both plan the same way: the preview shows the plan, and the apply plans again to
prove nothing moved since the listener approved it. The rules live in the domain; this gathers their inputs.
"""
from dataclasses import dataclass

from music_explorer.application.ports.taggable_tracks import TaggableTracks
from music_explorer.application.ports.track_tags import TrackTags, TrackTagsError
from music_explorer.domain.tag_change_set import TagChange, TrackTagEvidence, planned_track_changes


@dataclass(frozen=True)
class TagWritePlan:
    changes: tuple[TagChange, ...]
    skipped: tuple[tuple[str, str], ...]
    identities: tuple[tuple[str, str], ...]


def plan_tag_write(track_ids, *, policy, minimum_key_strength, tracks: TaggableTracks,
                   track_tags: TrackTags) -> TagWritePlan:
    changes, skipped, identities = [], [], []
    for track_id in track_ids:
        track = tracks.read(track_id)
        if track is None:
            skipped.append((track_id, 'Unknown track'))
            continue
        if track.location is None:
            skipped.append((track_id, 'No available catalogue location'))
            continue
        try:
            current = track_tags.read_owned(track.location)
        except TrackTagsError as error:
            skipped.append((track_id, str(error)))
            continue
        planned = planned_track_changes(_evidence(track), current_bpm=current.bpm, current_key=current.key,
                                        policy=policy, minimum_key_strength=minimum_key_strength)
        if not planned:
            skipped.append((track_id, 'Nothing to change'))
            continue
        changes.extend(planned)
        identities.append((track.location, track.sha256))
    return TagWritePlan(tuple(changes), tuple(skipped), tuple(identities))


def _evidence(track):
    return TrackTagEvidence(track.location, track.detected_bpm, track.tonic, track.scale, track.key_strength,
                            track.manual_bpm, track.manual_key)
