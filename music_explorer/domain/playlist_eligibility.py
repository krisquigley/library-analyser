"""Which tracks a playlist may use (#58, #120).

A track must be active, catalogued, present on disk at a safe path, and have a
detected BPM inside the requested range. A manual BPM annotation wins over
detection, and is text, not a tempo: the track has no usable BPM, exactly as
in the mood-axis graph.
"""
from dataclasses import dataclass
from math import isfinite


@dataclass(frozen=True)
class BpmRange:
    minimum: float
    maximum: float

    @classmethod
    def of(cls, minimum, maximum) -> 'BpmRange':
        """The range the listener asked for, from values as entered."""
        bpm_range = cls(_finite_bound(minimum, 'BPM minimum'), _finite_bound(maximum, 'BPM maximum'))
        if bpm_range.minimum > bpm_range.maximum:
            raise ValueError('bpm bounds must be ordered')
        return bpm_range

    def contains(self, bpm) -> bool:
        return _number(bpm) and isfinite(bpm) and self.minimum <= float(bpm) <= self.maximum


def eligible(track, bpm_range: BpmRange) -> bool:
    try:
        check_playable(track)
    except ValueError:
        return False
    return not bpm_overridden(track) and bpm_range.contains(track.bpm)


def check_start_track(start, bpm_range: BpmRange):
    """Say why the chosen start track cannot open the playlist."""
    check_playable(start, is_start=True)
    if bpm_overridden(start):
        raise ValueError('start track has a manual BPM override; its detected BPM is not used')
    if not bpm_range.contains(start.bpm):
        raise ValueError('start track BPM is outside requested range')


def bpm_overridden(track) -> bool:
    return 'bpm' in getattr(track, 'manual_overrides', ())


def check_playable(track, *, is_start=False):
    prefix = 'start track ' if is_start else ''
    if not getattr(track, 'active', True):
        raise ValueError(prefix + 'is not active/playable')
    if not getattr(track, 'catalogued', True):
        raise ValueError(prefix + 'is not catalogued/playable')
    if not getattr(track, 'exists', True):
        raise ValueError(prefix + 'path does not exist')
    path = str(getattr(track, 'path', '') or '')
    if not path or any(ord(ch) < 32 or ch == '\x7f' for ch in path):
        raise ValueError(prefix + 'path is not safe: control/newline injection rejected')


def _finite_bound(value, name):
    if value is None:
        raise ValueError(f'{name} bound is required')
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ValueError(f'{name} bound must be finite')
    if not isfinite(number):
        raise ValueError(f'{name} bound must be finite')
    return number


def _number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)
