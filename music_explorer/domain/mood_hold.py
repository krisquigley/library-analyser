"""Mood hold for playlists (#123): prefer tracks stronger in one mood."""
from dataclasses import dataclass
from typing import Mapping

from music_explorer.domain.percentile_rank import MIDDLE_LEVEL

MOOD_WEIGHT = 0.1


@dataclass(frozen=True)
class MoodHold:
    levels: Mapping[str, float]

    def adjustment(self, track_id: str) -> float:
        level = self.levels.get(track_id)
        return 0.0 if level is None else MOOD_WEIGHT * (level - MIDDLE_LEVEL)
