"""The BPM and key text a track's tags would hold (#132). A manual override wins over the detected value.

BPM is a whole number, as ID3's TBPM requires. The key uses the short standard names DJ software writes to
ID3's TKEY (at most three characters: "Am", "C#m", "Bb"). A detected key must reach the listener's minimum
key strength, because Essentia's strength is uncalibrated; a manual key is the listener's word and needs none.
Anything that cannot be read writes nothing.
"""
from math import floor, isfinite

from music_explorer.domain.harmonic_mixing import MusicalKey, usable_key

_MAJOR_NAMES = ('C', 'Db', 'D', 'Eb', 'E', 'F', 'F#', 'G', 'Ab', 'A', 'Bb', 'B')
_MINOR_NAMES = ('Cm', 'C#m', 'Dm', 'Ebm', 'Em', 'Fm', 'F#m', 'Gm', 'G#m', 'Am', 'Bbm', 'Bm')
_MANUAL_SCALES = {'': 'major', 'major': 'major', 'm': 'minor', 'minor': 'minor'}


def bpm_tag_value(detected, manual) -> str | None:
    bpm = _manual_bpm(manual) if manual is not None else detected
    if not _positive_number(bpm):
        return None
    return str(floor(bpm + 0.5))


def key_tag_value(tonic, scale, strength, manual, *, minimum_strength) -> str | None:
    if manual is not None:
        key = _manual_key(manual)
    else:
        key = usable_key(tonic, scale, strength, minimum_strength=minimum_strength)
    if key is None:
        return None
    return (_MAJOR_NAMES if key.scale == 'major' else _MINOR_NAMES)[key.pitch_class]


def _manual_bpm(text):
    try:
        return float(text.strip()) if isinstance(text, str) else None
    except ValueError:
        return None


def _manual_key(text):
    written = text.strip() if isinstance(text, str) else ''
    if not written:
        return None
    letter, rest = written[0].upper(), written[1:]
    accidental = rest[0] if rest[:1] in ('#', 'b') else ''
    scale = _MANUAL_SCALES.get(rest[len(accidental):].strip().lower())
    return MusicalKey.parse(letter + accidental, scale) if scale else None


def _positive_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and isfinite(value) and value > 0
