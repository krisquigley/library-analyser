"""Energy plan for playlist positions (#123, #135).

A plan is a chain of arcs. Each arc gives each position in its part of the
playlist (0 at the start, 1 at the end) a target energy level, anchored on the
track the arc starts from. Tracks off the target are nudged down, never excluded.
Levels are percentile ranks among the eligible tracks, from 0 to 1.

An arc may have an energy range (#136): rise heads for its high, fall for its
low, peak climbs to its high, and steady holds the start level within it. An
arc never heads the wrong way: a rise that starts above its high holds there.
Without a range, rise, fall and peak head for 0.9 and 0.1, and steady holds
the start level wherever it is.
"""
from dataclasses import dataclass
from math import isfinite
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


def _level(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and isfinite(value) and 0.0 <= value <= 1.0


@dataclass(frozen=True)
class EnergyRange:
    low: float = LOW_LEVEL
    high: float = HIGH_LEVEL

    def __post_init__(self):
        if not all(_level(value) for value in (self.low, self.high)):
            raise ValueError('Energy low and high must be between 0.0 and 1.0')
        if self.low >= self.high:
            raise ValueError('Energy low must be below energy high')

    @classmethod
    def of(cls, *, low: float | None, high: float | None) -> 'EnergyRange | None':
        """The range the listener set, defaulting an unset end; None when neither is set."""
        if low is None and high is None:
            return None
        return cls(LOW_LEVEL if low is None else low, HIGH_LEVEL if high is None else high)

    def clamp(self, level: float) -> float:
        return min(max(level, self.low), self.high)


DEFAULT_RANGE = EnergyRange()


def arc_target(shape: str, start_level: float, position: float, energy_range: EnergyRange | None = None) -> float:
    _check_shape(shape)
    bounds = energy_range or DEFAULT_RANGE
    if shape == 'rise':
        return _towards(start_level, max(start_level, bounds.high), position)
    if shape == 'fall':
        return _towards(start_level, min(start_level, bounds.low), position)
    if shape == 'peak':
        summit = max(start_level, bounds.high)
        if position <= PEAK_POSITION:
            return _towards(start_level, summit, position / PEAK_POSITION)
        return _towards(summit, start_level, (position - PEAK_POSITION) / (1 - PEAK_POSITION))
    return start_level if energy_range is None else energy_range.clamp(start_level)


@dataclass(frozen=True)
class ArcSegment:
    shape: str
    energy_range: EnergyRange | None = None

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
        return -ARC_WEIGHT * abs(level - self._target(start_level, position))

    def _target(self, start_level, position):
        arc = self.segments[0]
        return arc_target(arc.shape, start_level, position, arc.energy_range)


def _towards(start, end, progress):
    return start + (end - start) * min(max(progress, 0.0), 1.0)


def _check_shape(shape):
    if shape not in ARC_SHAPES:
        raise ValueError('Energy arc must be steady, rise, fall or peak')
