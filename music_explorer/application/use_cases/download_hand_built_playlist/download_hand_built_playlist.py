"""Download a playlist the listener built by hand from the graph (#277) as an M3U, in their order.

Unlike a recipe's walk, nothing is chosen here: each named track must still be playable from the library.
"""
from dataclasses import dataclass

from music_explorer.application.dto.playlists import M3UPlaylist
from music_explorer.application.ports.playlist_export_tracks import PlaylistExportTracks

MAXIMUM_HAND_BUILT_TRACKS = 500
MAXIMUM_TRACK_ID_LENGTH = 256


class HandBuiltPlaylistRequestError(ValueError):
    pass


@dataclass(frozen=True)
class DownloadHandBuiltPlaylistRequest:
    track_ids: tuple[str, ...]


class DownloadHandBuiltPlaylist:
    def __init__(self, tracks: PlaylistExportTracks):
        self._tracks = tracks

    def execute(self, request: DownloadHandBuiltPlaylistRequest) -> M3UPlaylist:
        _check(request.track_ids)
        playable = {track.track_id: track for track in self._tracks.playlist_export_tracks() if _playable(track)}
        for place, track_id in enumerate(request.track_ids, start=1):
            if track_id not in playable:
                raise HandBuiltPlaylistRequestError(
                    f'Track {place} of the playlist is no longer playable from the library; remove it and try again')
        content = '#EXTM3U\n' + ''.join(playable[track_id].path + '\n' for track_id in request.track_ids)
        return M3UPlaylist(content, request.track_ids)


def _check(track_ids):
    if not track_ids:
        raise HandBuiltPlaylistRequestError('Add at least one track to the playlist')
    if len(track_ids) > MAXIMUM_HAND_BUILT_TRACKS:
        raise HandBuiltPlaylistRequestError(f'A playlist holds at most {MAXIMUM_HAND_BUILT_TRACKS} tracks')
    if not all(_is_track_id(track_id) for track_id in track_ids):
        raise HandBuiltPlaylistRequestError(f'A track ID must be text of 1 to {MAXIMUM_TRACK_ID_LENGTH} characters')
    if len(set(track_ids)) != len(track_ids):
        raise HandBuiltPlaylistRequestError('The playlist names a track more than once')


def _is_track_id(value):
    return isinstance(value, str) and 0 < len(value) <= MAXIMUM_TRACK_ID_LENGTH and '\x00' not in value


def _playable(track):
    return track.exists and track.active and track.catalogued
