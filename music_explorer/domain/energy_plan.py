"""Energy plan for playlist positions (#123, #135, #137).

A plan is a chain of arcs played in order. Each arc lasts a number of tracks or
a duration, in the playlist's own unit, and gives each place in its part of the
playlist (0 at its start, 1 at its end) a target energy level. Tracks off the
target are nudged down, never excluded. Levels are raw arousal, the numbers
the graph shows (#265); the eligible tracks' ArousalScale gives the defaults,
the middle and the span a miss is measured against.

The first arc is anchored on the start track. Each later arc starts from the
energy actually reached: the level of the last track placed before it began,
or, when that track's energy is unknown, the previous arc's planned end. The
anchor is read from the walk, so it follows the search when it backtracks. By
duration, a track belongs to the arc in which it starts.

An arc may have an energy range (#136): rise heads for its high, fall for its
low, peak climbs to its high and dip sinks to its low, both coming back to the
level they started from, and steady holds the start level within the range. An
arc never heads the wrong way: a rise that starts above its high holds there.
Without a range, the arcs head for the library's defaults (the arousal at the
eligible tracks' 90th and 10th percentiles), and steady holds the start level
wherever it is.
"""
from dataclasses import dataclass
from math import isfinite
from typing import Mapping, Sequence

from music_explorer.domain.arousal_scale import ArousalScale

ARC_SHAPES = ('steady', 'rise', 'fall', 'peak', 'dip')
# Where a peak reaches its summit and a dip its trough.
TURN_POSITION = 2 / 3
# Chosen from aggregate measurements on a ~3.4k-track library: at 0.2 the
# graph's pull between related tracks swamped rise and peak; at 0.6 a 30-track
# arc misses its target by about 0.06 on average, with no loss in the mean
# relation score of its transitions. Higher weights gained little.
ARC_WEIGHT = 0.6
UNKNOWN_ENERGY_MISS = 0.25


def _arousal(value):
    return value is None or (isinstance(value, (int, float)) and not isinstance(value, bool) and isfinite(value))


@dataclass(frozen=True)
class EnergyRange:
    """How low and how high an arc goes, in raw arousal (#265), as the listener set it; an unset end is None."""
    low: float | None = None
    high: float | None = None

    def __post_init__(self):
        if not all(_arousal(value) for value in (self.low, self.high)):
            raise ValueError('Energy low and high must be numbers')
        if self.low is not None and self.high is not None and self.low >= self.high:
            raise ValueError('Energy low must be below energy high')

    @classmethod
    def of(cls, *, low: float | None, high: float | None) -> 'EnergyRange | None':
        """The range the listener set; None when neither end is set."""
        if low is None and high is None:
            return None
        return cls(low, high)

    def bounds(self, scale: ArousalScale) -> tuple[float, float]:
        """The (low, high) the arc heads for, an unset end taking the library's default."""
        low = scale.low if self.low is None else self.low
        high = scale.high if self.high is None else self.high
        if low >= high:
            raise ValueError(f'Energy low {low:.2f} must be below energy high {high:.2f}')
        return low, high


def arc_target(shape: str, start_level: float, position: float, energy_range: EnergyRange | None,
               scale: ArousalScale) -> float:
    _check_shape(shape)
    low, high = energy_range.bounds(scale) if energy_range else (scale.low, scale.high)
    if shape == 'rise':
        return _towards(start_level, max(start_level, high), position)
    if shape == 'fall':
        return _towards(start_level, min(start_level, low), position)
    if shape == 'peak':
        return _there_and_back(start_level, max(start_level, high), position)
    if shape == 'dip':
        return _there_and_back(start_level, min(start_level, low), position)
    return start_level if energy_range is None else min(max(start_level, low), high)


@dataclass(frozen=True)
class ArcSegment:
    """An arc's shape, its length in the plan's unit, and its energy range."""
    shape: str
    length: float
    energy_range: EnergyRange | None = None

    def __post_init__(self):
        _check_shape(self.shape)


class _TrackCountTimeline:
    """Places count tracks: the start track is 0, the next 1, and so on."""

    def starts(self, walk):
        return range(len(walk) + 1)

    def check(self, length):
        if not (_number(length) and length == int(length) and length >= 1):
            raise ValueError('An arc length must be a whole number of tracks, at least 1')

    def position(self, place, span, anchor_place):
        # From the anchor to the arc's last track; the first arc's anchor is its own first track.
        last = span.start + span.length - 1
        return (place - anchor_place) / (last - anchor_place) if last > anchor_place else 1.0


class _DurationTimeline:
    """Places are the seconds at which tracks start."""

    def starts(self, walk):
        elapsed = [0.0]
        for track in walk:
            elapsed.append(elapsed[-1] + track.duration_seconds)
        return elapsed

    def check(self, length):
        if not (_number(length) and isfinite(length) and length > 0):
            raise ValueError('An arc length must be a positive duration')

    def position(self, place, span, anchor_place):
        return (place - span.start) / span.length


BY_TRACK_COUNT = _TrackCountTimeline()
BY_DURATION = _DurationTimeline()


@dataclass(frozen=True)
class _Span:
    start: float
    length: float


@dataclass(frozen=True)
class EnergyPlan:
    segments: tuple[ArcSegment, ...]
    levels: Mapping[str, float]
    timeline: _TrackCountTimeline | _DurationTimeline
    scale: ArousalScale

    def __post_init__(self):
        if not self.segments:
            raise ValueError('An energy plan has at least one arc')
        for arc in self.segments:
            self.timeline.check(arc.length)
            if arc.energy_range:
                arc.energy_range.bounds(self.scale)

    def target_after(self, walk: Sequence) -> float:
        """The energy level the plan wants from the track placed after `walk`."""
        starts = self.timeline.starts(walk)
        spans = self._spans()
        place = starts[-1]
        index = max(i for i, span in enumerate(spans) if i == 0 or span.start <= place)
        anchor = self._anchor(index, walk, starts, spans)
        position = min(max(self.timeline.position(place, spans[index], starts[anchor]), 0.0), 1.0)
        return self._arc_target(index, self._anchor_level(index, walk, starts, spans), position)

    def targets_along(self, walk: Sequence) -> tuple[float, ...]:
        """The target each placed track was chosen for; the start track's is where the first arc begins."""
        if not walk:
            return ()
        start = self._arc_target(0, self._anchor_level(0, walk[:1], self.timeline.starts(walk[:1]), self._spans()), 0.0)
        return (start,) + tuple(self.target_after(walk[:place]) for place in range(1, len(walk)))

    def miss(self, track_id: str, target: float) -> float:
        """How far `track_id` misses `target`, as a ranking adjustment."""
        level = self.levels.get(track_id)
        if level is None:
            return -ARC_WEIGHT * UNKNOWN_ENERGY_MISS
        return -ARC_WEIGHT * abs(level - target) / self.scale.span

    def _spans(self):
        spans, start = [], 0
        for arc in self.segments:
            spans.append(_Span(start, arc.length))
            start += arc.length
        return spans

    def _anchor(self, index, walk, starts, spans):
        """The walk's index of the track an arc starts from: the last one placed before the arc began."""
        if index == 0:
            return 0
        return max(i for i in range(len(walk)) if starts[i] < spans[index].start)

    def _anchor_level(self, index, walk, starts, spans):
        level = self.levels.get(walk[self._anchor(index, walk, starts, spans)].track_id)
        if level is not None:
            return level
        if index == 0:
            return self.scale.middle
        return self._arc_target(index - 1, self._anchor_level(index - 1, walk, starts, spans), 1.0)

    def _arc_target(self, index, start_level, position):
        arc = self.segments[index]
        return arc_target(arc.shape, start_level, position, arc.energy_range, self.scale)


def _number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _towards(start, end, progress):
    return start + (end - start) * min(max(progress, 0.0), 1.0)


def _there_and_back(start, turn, position):
    if position <= TURN_POSITION:
        return _towards(start, turn, position / TURN_POSITION)
    return _towards(turn, start, (position - TURN_POSITION) / (1 - TURN_POSITION))


def _check_shape(shape):
    if shape not in ARC_SHAPES:
        raise ValueError('Energy arc must be steady, rise, fall, peak or dip')
