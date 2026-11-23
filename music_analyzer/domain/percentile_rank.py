"""Levels as percentile mid-ranks (#134), the same rule as the Explorer's (#123).

Valence and arousal are uncalibrated emomusic regression coordinates, so the export compares them as
levels: each value's rank among the tracks being exported. The analyzer keeps its own copy of the rule,
because the two packages never import each other; a contract test keeps the copies the same.
"""
from typing import Mapping

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
