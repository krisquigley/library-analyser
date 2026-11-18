"""Levels as percentile mid-ranks (#123).

Model scores such as arousal are uncalibrated regression coordinates, so a
playlist compares them as levels: each value's rank among the eligible tracks.
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
