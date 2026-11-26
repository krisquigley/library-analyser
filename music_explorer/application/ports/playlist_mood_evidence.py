"""Reading each track's usable arousal and, for a held mood, its score (#120, #287)."""
from collections.abc import Mapping
from typing import Protocol

from music_explorer.application.dto.playlists import PlaylistMoodEvidence


class PlaylistMoodEvidenceSource(Protocol):
    def playlist_mood_evidence(self, mood: str | None) -> Mapping[str, PlaylistMoodEvidence]: ...
