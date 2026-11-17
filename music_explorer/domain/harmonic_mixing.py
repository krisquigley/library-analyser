"""Harmonic mixing rules for playlist transitions (#122).

Keys are compared on the Camelot wheel. A transition between related tracks
is nudged up for a compatible key and down for an incompatible key or a large
BPM step. Nothing is excluded: harmony steers the walk, it never cuts it short.
Essentia's key strength is uncalibrated, so the minimum that makes a key
usable is the listener's setting.
"""
from dataclasses import dataclass
from math import isfinite

DEFAULT_MINIMUM_KEY_STRENGTH = 0.5
DEFAULT_BPM_STEP_TOLERANCE = 0.06
# Graph relation scores mostly span about 0.8-0.95, so 0.05 steers the walk
# without letting harmony outweigh how related two tracks are.
KEY_ADJUSTMENT = 0.05
BPM_STEP_PENALTY = 0.05

_PITCH_CLASSES = {'C': 0, 'C#': 1, 'Db': 1, 'D': 2, 'D#': 3, 'Eb': 3, 'E': 4, 'F': 5, 'F#': 6, 'Gb': 6,
                  'G': 7, 'G#': 8, 'Ab': 8, 'A': 9, 'A#': 10, 'Bb': 10, 'B': 11}


@dataclass(frozen=True)
class MusicalKey:
    pitch_class: int
    scale: str

    @classmethod
    def parse(cls, tonic, scale):
        scale = scale.lower() if isinstance(scale, str) else None
        if tonic not in _PITCH_CLASSES or scale not in ('major', 'minor'):
            return None
        return cls(_PITCH_CLASSES[tonic], scale)


def camelot_code(key: MusicalKey) -> str:
    number, letter = _camelot(key)
    return f'{number}{letter}'


def keys_compatible(a: MusicalKey, b: MusicalKey) -> bool:
    (number_a, letter_a), (number_b, letter_b) = _camelot(a), _camelot(b)
    if letter_a != letter_b:
        return number_a == number_b
    return (number_a - number_b) % 12 in (0, 1, 11)


def usable_key(tonic, scale, strength, *, minimum_strength):
    if not _number(strength) or strength <= 0 or strength < minimum_strength:
        return None
    return MusicalKey.parse(tonic, scale)


@dataclass(frozen=True)
class HarmonicMixing:
    minimum_key_strength: float = DEFAULT_MINIMUM_KEY_STRENGTH
    bpm_step_tolerance: float = DEFAULT_BPM_STEP_TOLERANCE

    def __post_init__(self):
        if not _number(self.minimum_key_strength) or not 0.0 <= self.minimum_key_strength <= 1.0:
            raise ValueError('Minimum key strength must be between 0.0 and 1.0')

    def transition_score(self, relation_score, from_key, to_key, from_bpm, to_bpm):
        return relation_score + self._key_adjustment(from_key, to_key) - self._bpm_step_penalty(from_bpm, to_bpm)

    @staticmethod
    def _key_adjustment(from_key, to_key):
        if from_key is None or to_key is None:
            return 0.0
        return KEY_ADJUSTMENT if keys_compatible(from_key, to_key) else -KEY_ADJUSTMENT

    def _bpm_step_penalty(self, from_bpm, to_bpm):
        if not (_number(from_bpm) and _number(to_bpm)) or min(from_bpm, to_bpm) <= 0:
            return 0.0
        step = abs(to_bpm - from_bpm) / min(from_bpm, to_bpm)
        # Rounding keeps a step of exactly the tolerance (100 -> 106) smooth.
        return BPM_STEP_PENALTY if round(step, 9) > self.bpm_step_tolerance else 0.0


def _camelot(key):
    # The wheel advances one step per fifth (7 semitones); C major is 8B, and a
    # minor key shares its number with its relative major (3 semitones up).
    major_tonic = key.pitch_class if key.scale == 'major' else (key.pitch_class + 3) % 12
    number = (7 * major_tonic + 7) % 12 + 1
    return number, 'B' if key.scale == 'major' else 'A'


def _number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and isfinite(value)
