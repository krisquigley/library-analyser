"""Energy plan for playlist positions (#123, #135).

A plan is a chain of arcs. Each arc gives each position in its part of the
playlist (0 at the start, 1 at the end) a target energy level, anchored on the
track the arc starts from. Tracks off the target are nudged down, never excluded.
Levels are percentile ranks among the eligible tracks.
"""
from dataclasses import dataclass
from typing import Mapping, Sequence

from music_explorer.domain.percentile_rank import MIDDLE_LEVEL

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
class ArcSegment:
    shape: str

    def __post_init__(self):
        _check_shape(self.shape)


@dataclass(frozen=True)
class EnergyPlan:
    segments: tuple[ArcSegment, ...]
    levels: Mapping[str, float]

    def __post_init__(self):
        if len(self.segments) != 1:
            raise ValueError('An energy plan has one arc until arcs can be chained')

    def adjustment(self, walk: Sequence, track_id: str, position: float) -> float:
        """How far `track_id`, placed after `walk` at `position`, misses the plan's target."""
        level = self.levels.get(track_id)
        if level is None:
            return -ARC_WEIGHT * UNKNOWN_ENERGY_MISS
        start_level = self.levels.get(walk[0].track_id, MIDDLE_LEVEL)
        return -ARC_WEIGHT * abs(level - arc_target(self.segments[0].shape, start_level, position))


def _towards(start, end, progress):
    return start + (end - start) * min(max(progress, 0.0), 1.0)


def _check_shape(shape):
    if shape not in ARC_SHAPES:
        raise ValueError('Energy arc must be steady, rise, fall or peak')
