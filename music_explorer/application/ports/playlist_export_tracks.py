"""Reading the tracks a playlist can hold, with where each one's audio is (#277)."""
from typing import Protocol

from music_explorer.application.dto.playlists import PlayableTrackCandidate


class PlaylistExportTracks(Protocol):
    def playlist_export_tracks(self) -> tuple[PlayableTrackCandidate, ...]: ...
