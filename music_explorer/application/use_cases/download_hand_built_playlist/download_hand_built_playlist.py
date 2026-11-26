"""Download a playlist the listener built by hand from the graph (#277) as an M3U, in their order.

Unlike a recipe's walk, nothing is chosen here: each named track must still be playable from the library.
"""
from dataclasses import dataclass

from music_explorer.application.dto.playlists import M3UPlaylist
from music_explorer.application.ports.playlist_export_tracks import PlaylistExportTracks
from music_explorer.domain.hand_built_playlist import HandBuiltPlaylistError, hand_built_track_ids


@dataclass(frozen=True)
class DownloadHandBuiltPlaylistRequest:
    track_ids: tuple[str, ...]


class DownloadHandBuiltPlaylist:
    def __init__(self, tracks: PlaylistExportTracks):
        self._tracks = tracks

    def execute(self, request: DownloadHandBuiltPlaylistRequest) -> M3UPlaylist:
        track_ids = hand_built_track_ids(request.track_ids)
        playable = {track.track_id: track for track in self._tracks.playlist_export_tracks() if _playable(track)}
        for place, track_id in enumerate(track_ids, start=1):
            if track_id not in playable:
                raise HandBuiltPlaylistError(
                    f'Track {place} of the playlist is no longer playable from the library; remove it and try again')
        content = '#EXTM3U\n' + ''.join(playable[track_id].path + '\n' for track_id in track_ids)
        return M3UPlaylist(content, track_ids)


def _playable(track):
    return track.exists and track.active and track.catalogued
