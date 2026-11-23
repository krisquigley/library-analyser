"""How an analysed track's evidence becomes a row in a new Mixxx-compatible library file (#133).

The encoding follows Mixxx 2.5 (schema revision 39), read from its public source: `key_id` is the
ChromaticKey enum (src/proto/keys.proto: 0 unknown, 1-12 C to B major, 13-24 C to B minor), the key text
uses Mixxx's ID3v2 names (src/track/keyutils.cpp), and an unknown BPM is 0.0 (src/track/bpm.h).
Mixxx shows the key from `key_id` when it is known, so the text only matters where `key_id` is not.
Anything that cannot be read is left empty, never guessed.
"""
from __future__ import annotations

from dataclasses import dataclass
import math

_PITCH_CLASSES = {'C': 0, 'C#': 1, 'Db': 1, 'D': 2, 'D#': 3, 'Eb': 3, 'E': 4, 'F': 5, 'F#': 6, 'Gb': 6,
                  'G': 7, 'G#': 8, 'Ab': 8, 'A': 9, 'A#': 10, 'Bb': 10, 'B': 11}
_MAJOR_NAMES = ('C', 'Db', 'D', 'Eb', 'E', 'F', 'F#', 'G', 'Ab', 'A', 'Bb', 'B')
_MINOR_NAMES = ('Cm', 'C#m', 'Dm', 'Ebm', 'Em', 'Fm', 'F#m', 'Gm', 'G#m', 'Am', 'Bbm', 'Bm')
_SCALE_WORDS = {'major': 'major', 'minor': 'minor', 'm': 'minor', '': 'major'}
UNKNOWN_BPM = 0.0
UNKNOWN_FILE_TYPE = '?'


@dataclass(frozen=True)
class MixxxKey:
    key_id: int
    text: str


UNKNOWN_KEY = MixxxKey(0, '')


@dataclass(frozen=True)
class TrackLocation:
    location: str
    filename: str
    directory: str


@dataclass(frozen=True)
class MixxxTrack:
    """One row of the new library file: where the track is, what it is, and its tempo and key."""
    location: TrackLocation
    filesize: int
    title: str
    artist: str
    album: str
    duration: float
    bpm: float
    key: MixxxKey
    file_type: str
    color: int | None = None


class MixxxExportError(ValueError):
    """The export cannot be made as asked; the message says what to change."""


def mixxx_key(tonic, scale) -> MixxxKey:
    """A detected key (tonic and scale, as Essentia names them) in Mixxx's encoding."""
    if tonic not in _PITCH_CLASSES or not isinstance(scale, str) or scale.lower() not in ('major', 'minor'):
        return UNKNOWN_KEY
    pitch_class = _PITCH_CLASSES[tonic]
    if scale.lower() == 'major':
        return MixxxKey(pitch_class + 1, _MAJOR_NAMES[pitch_class])
    return MixxxKey(pitch_class + 13, _MINOR_NAMES[pitch_class])


def mixxx_key_from_text(text) -> MixxxKey:
    """A manual key override, written as "A minor", "Am", "C#m" or "Bb"."""
    if not isinstance(text, str) or not text.strip():
        return UNKNOWN_KEY
    written = text.strip()
    letter, rest = written[0].upper(), written[1:]
    accidental = rest[0] if rest[:1] in ('#', 'b') else ''
    scale = _SCALE_WORDS.get(rest[len(accidental):].strip().lower())
    return mixxx_key(letter + accidental, scale) if scale else UNKNOWN_KEY


def mixxx_bpm(value) -> float:
    """A BPM Mixxx accepts (finite and above zero), or Mixxx's own 0.0 for unknown."""
    if isinstance(value, bool):
        return UNKNOWN_BPM
    try:
        bpm = float(value.strip() if isinstance(value, str) else value)
    except (TypeError, ValueError):
        return UNKNOWN_BPM
    return bpm if math.isfinite(bpm) and bpm > 0 else UNKNOWN_BPM


def track_location(path: str) -> TrackLocation:
    """Where Mixxx finds the file: its absolute path, the file's name and its folder."""
    if not isinstance(path, str) or not path.startswith('/') or path.endswith('/'):
        raise ValueError('A track location must be an absolute path to a file')
    directory, filename = path.rsplit('/', 1)
    return TrackLocation(path, filename, directory or '/')


def mixxx_file_type(filename: str) -> str:
    """The file type Mixxx records (its lowercase extension, "aif" spelt "aiff" since revision 39), or its "?"."""
    stem, dot, extension = filename.rpartition('.')
    extension = extension.lower()
    if not dot or not stem or not extension or len(extension) > 8:
        return UNKNOWN_FILE_TYPE
    return 'aiff' if extension == 'aif' else extension
