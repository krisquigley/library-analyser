"""Energy arc and mood hold for playlist positions (#123).

Stored arousal is a native emomusic regression coordinate, not a 0-1 scale,
so energy is compared as a level: the track's percentile rank among the
eligible tracks. An arc gives each position in the playlist (0 at the start,
1 at the end) a target level anchored on the start track. Tracks off the
target are nudged down, never excluded.
"""
from dataclasses import dataclass, field
from typing import Mapping

ARC_SHAPES = ('steady', 'rise', 'fall', 'peak')
HIGH_LEVEL = 0.9
LOW_LEVEL = 0.1
PEAK_POSITION = 2 / 3
# Chosen from aggregate measurements on a ~3.4k-track library: at 0.2 the
# graph's pull between related tracks swamped rise and peak; at 0.6 a 30-track
# arc misses its target by about 0.06 on average, with no loss in the mean
# relation score of its transitions. Higher weights gained little.
ARC_WEIGHT = 0.6
UNKNOWN_ENERGY_MISS = 0.25
MOOD_WEIGHT = 0.1
MIDDLE_LEVEL = 0.5


def percentile_ranks(values: Mapping[str, float]) -> dict[str, float]:
    """Each value's mid-rank among all values, from 0 (lowest) to 1 (highest)."""
    ordered = sorted(values.values())
    if len(ordered) == 1:
        return {track_id: MIDDLE_LEVEL for track_id in values}
    first_index, last_index = {}, {}
    for index, value in enumerate(ordered):
        first_index.setdefault(value, index)
        last_index[value] = index
    top = len(ordered) - 1
    return {track_id: (first_index[value] + last_index[value]) / 2 / top for track_id, value in values.items()}


def arc_target(shape: str, start_level: float, position: float) -> float:
    _check_shape(shape)
    if shape == 'rise':
        return _towards(start_level, max(start_level, HIGH_LEVEL), position)
    if shape == 'fall':
        return _towards(start_level, min(start_level, LOW_LEVEL), position)
    if shape == 'peak':
        summit = max(start_level, HIGH_LEVEL)
        if position <= PEAK_POSITION:
            return _towards(start_level, summit, position / PEAK_POSITION)
        return _towards(summit, start_level, (position - PEAK_POSITION) / (1 - PEAK_POSITION))
    return start_level


@dataclass(frozen=True)
class EnergyArc:
    shape: str
    levels: Mapping[str, float]
    start_track_id: str
    start_level: float = field(init=False)

    def __post_init__(self):
        _check_shape(self.shape)
        object.__setattr__(self, 'start_level', self.levels.get(self.start_track_id, MIDDLE_LEVEL))

    def adjustment(self, track_id: str, position: float) -> float:
        level = self.levels.get(track_id)
        miss = UNKNOWN_ENERGY_MISS if level is None else abs(level - arc_target(self.shape, self.start_level, position))
        return -ARC_WEIGHT * miss


@dataclass(frozen=True)
class MoodHold:
    levels: Mapping[str, float]

    def adjustment(self, track_id: str) -> float:
        level = self.levels.get(track_id)
        return 0.0 if level is None else MOOD_WEIGHT * (level - MIDDLE_LEVEL)


def _towards(start, end, progress):
    return start + (end - start) * min(max(progress, 0.0), 1.0)


def _check_shape(shape):
    if shape not in ARC_SHAPES:
        raise ValueError('Energy arc must be steady, rise, fall or peak')
