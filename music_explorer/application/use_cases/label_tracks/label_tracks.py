"""Label the tracks around a selection in the graph (#243): the title and artist of each track named, by ID.

The page asks once per selection, for the selected track and its nearest neighbours.
"""
from dataclasses import dataclass

from music_explorer.application.ports.track_summaries import TrackSummariesById

MAXIMUM_TRACKS_PER_LABEL_REQUEST = 100
MAXIMUM_TRACK_ID_LENGTH = 256


class TrackLabelRequestError(ValueError):
    pass


@dataclass(frozen=True)
class LabelTracksRequest:
    track_ids: tuple[str, ...]


@dataclass(frozen=True)
class TrackLabel:
    track_id: str
    title: str
    artist: str


class LabelTracks:
    def __init__(self, tracks: TrackSummariesById):
        self._tracks = tracks

    def execute(self, request: LabelTracksRequest) -> tuple[TrackLabel, ...]:
        _check(request.track_ids)
        found = {summary.handle: summary for summary in self._tracks.track_summaries(request.track_ids)}
        return tuple(TrackLabel(track_id, found[track_id].title, found[track_id].artist)
                     for track_id in request.track_ids if track_id in found)


def _check(track_ids):
    if not track_ids:
        raise TrackLabelRequestError('Name at least one track')
    if len(track_ids) > MAXIMUM_TRACKS_PER_LABEL_REQUEST:
        raise TrackLabelRequestError(f'Name at most {MAXIMUM_TRACKS_PER_LABEL_REQUEST} tracks')
    if not all(_is_track_id(track_id) for track_id in track_ids):
        raise TrackLabelRequestError(f'A track ID must be text of 1 to {MAXIMUM_TRACK_ID_LENGTH} characters')
    if len(set(track_ids)) != len(track_ids):
        raise TrackLabelRequestError('Name each track once')


def _is_track_id(value):
    return isinstance(value, str) and 0 < len(value) <= MAXIMUM_TRACK_ID_LENGTH and '\x00' not in value
