"""Where the eligible tracks' arousal lies (#265), in the graph's own numbers.

Arousal is an uncalibrated emomusic regression coordinate, so an energy arc's
defaults come from the library itself: an arc without a range heads for the
arousal at the 10th or 90th percentile of the tracks eligible for the playlist,
and an unknown start is taken to be at their median. A miss is measured as a
share of their span, so the arc weight means the same in any library.
"""
from dataclasses import dataclass
from typing import Iterable

LOW_PERCENTILE = 0.1
HIGH_PERCENTILE = 0.9


@dataclass(frozen=True)
class ArousalScale:
    low: float
    high: float
    middle: float
    span: float

    @classmethod
    def of(cls, arousal: Iterable[float]) -> 'ArousalScale':
        ordered = sorted(arousal)
        if not ordered:
            return cls(0.0, 1.0, 0.5, 1.0)
        span = ordered[-1] - ordered[0]
        return cls(_at(ordered, LOW_PERCENTILE), _at(ordered, HIGH_PERCENTILE), _at(ordered, 0.5), span if span > 0 else 1.0)


def _at(ordered, fraction):
    """The value `fraction` of the way through the ordered values, between neighbours where it falls."""
    place = fraction * (len(ordered) - 1)
    below = int(place)
    above = min(below + 1, len(ordered) - 1)
    return ordered[below] + (ordered[above] - ordered[below]) * (place - below)
