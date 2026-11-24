"""Listen to a track from the Explorer (#258): its first available audio file, read as it is.

The listener names a track by its ID; the file comes from the analysis database, never from the request.
Audio is only read, never written.
"""
from dataclasses import dataclass

from music_explorer.application.ports.track_audio_locations import TrackAudioLocations

MAXIMUM_TRACK_ID_LENGTH = 256


class TrackAudioRequestError(ValueError):
    pass


class TrackAudioUnavailableError(LookupError):
    pass


@dataclass(frozen=True)
class ListenToTrackRequest:
    track_id: str


@dataclass(frozen=True)
class TrackAudio:
    track_id: str
    location: str


class ListenToTrack:
    def __init__(self, locations: TrackAudioLocations):
        self._locations = locations

    def execute(self, request: ListenToTrackRequest) -> TrackAudio:
        _check(request.track_id)
        location = self._locations.first_available_location(request.track_id)
        if location is None:
            raise TrackAudioUnavailableError('This track has no available audio file')
        return TrackAudio(request.track_id, location)


def _check(track_id):
    if (not isinstance(track_id, str) or not track_id.strip() or len(track_id) > MAXIMUM_TRACK_ID_LENGTH
            or '\x00' in track_id):
        raise TrackAudioRequestError('Name one track to listen to')
