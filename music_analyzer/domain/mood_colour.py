"""A track's mood quadrant as a Mixxx track colour (#134; owner decision: mood quadrant, 4 colours).

Levels are percentile mid-ranks of valence and arousal among the exported tracks, so the median splits
each axis. A track exactly at the median on either axis belongs to no quadrant and gets no colour.
Colours are 24-bit RGB integers, as Mixxx stores `library.color`.
"""
from dataclasses import dataclass

MEDIAN_LEVEL = 0.5


@dataclass(frozen=True)
class MoodQuadrant:
    name: str
    rgb: int


UPBEAT = MoodQuadrant('upbeat (high arousal, high valence)', 0xF8D200)
TENSE = MoodQuadrant('tense (high arousal, low valence)', 0xC50A08)
CALM = MoodQuadrant('calm (low arousal, high valence)', 0x32BE44)
SOMBRE = MoodQuadrant('sombre (low arousal, low valence)', 0x0044FF)
MOOD_QUADRANTS = (UPBEAT, TENSE, CALM, SOMBRE)


def mood_quadrant(valence_level: float, arousal_level: float) -> MoodQuadrant | None:
    if valence_level == MEDIAN_LEVEL or arousal_level == MEDIAN_LEVEL:
        return None
    if arousal_level > MEDIAN_LEVEL:
        return UPBEAT if valence_level > MEDIAN_LEVEL else TENSE
    return CALM if valence_level > MEDIAN_LEVEL else SOMBRE
