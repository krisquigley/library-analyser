"""Saved playlist recipes (#139): a versioned document, checked in full before the analyzer stores it.

The analyzer stores recipes and the Explorer reads them, so this format is a contract between the two
packages. Every field is checked, unknown fields are rejected and nothing is coerced: a value of the wrong
kind is an error the listener can act on, named by its place in the document.
"""
from __future__ import annotations

from dataclasses import dataclass
import math

FORMAT = 'playlist-recipe'
# Version 2 (#265): an arc's energy_low and energy_high are raw arousal, as the graph shows it, not 0-1 ranks.
VERSION = 2
ARC_SHAPES = ('steady', 'rise', 'fall', 'peak', 'dip')
MAXIMUM_TRACKS = 1000
MAXIMUM_MINUTES = 1440
MAXIMUM_NAME_LENGTH = 100
DEFAULT_MINIMUM_KEY_STRENGTH = 0.5
LENGTH_UNITS = ('tracks', 'minutes')

_RECIPE_FIELDS = ('format', 'version', 'start_track_id', 'bpm', 'length', 'harmonic_mixing', 'energy_plan', 'mood_hold')
_ARC_FIELDS = ('shape', 'tracks', 'minutes', 'energy_low', 'energy_high')


class PlaylistRecipeError(ValueError):
    """A recipe document, or a recipe's name, that cannot be stored."""


@dataclass(frozen=True)
class EnergyArc:
    shape: str
    length: tuple[str, float | int] | None
    energy_low: float | None
    energy_high: float | None

    def to_document(self) -> dict:
        document = {'shape': self.shape}
        if self.length is not None:
            document[self.length[0]] = self.length[1]
        return {**document, 'energy_low': self.energy_low, 'energy_high': self.energy_high}


@dataclass(frozen=True)
class PlaylistRecipe:
    start_track_id: str
    bpm_min: float
    bpm_max: float
    length: tuple[str, float | int] | None
    harmonic_mixing: bool
    minimum_key_strength: float
    energy_plan: tuple[EnergyArc, ...]
    mood_hold: str | None

    def to_document(self) -> dict:
        document = {'format': FORMAT, 'version': VERSION, 'start_track_id': self.start_track_id,
                    'bpm': {'min': self.bpm_min, 'max': self.bpm_max}}
        if self.length is not None:
            document['length'] = {self.length[0]: self.length[1]}
        return {**document,
                'harmonic_mixing': {'enabled': self.harmonic_mixing, 'minimum_key_strength': self.minimum_key_strength},
                'energy_plan': [arc.to_document() for arc in self.energy_plan], 'mood_hold': self.mood_hold}


def playlist_recipe_name(name) -> str:
    trimmed = name.strip() if isinstance(name, str) else ''
    if not 1 <= len(trimmed) <= MAXIMUM_NAME_LENGTH or not trimmed.isprintable():
        raise PlaylistRecipeError(f'A recipe name is 1 to {MAXIMUM_NAME_LENGTH} printable characters')
    return trimmed


def parse_playlist_recipe(document) -> PlaylistRecipe:
    _check_object(document, 'The recipe', _RECIPE_FIELDS, '')
    _check_format(document)
    bpm_min, bpm_max = _bpm(_required(document, 'bpm'))
    energy_plan = _energy_plan(document.get('energy_plan', []))
    enabled, minimum_key_strength = _harmonic_mixing(document.get('harmonic_mixing', {}))
    return PlaylistRecipe(
        start_track_id=_text(_required(document, 'start_track_id'), 'start_track_id must be non-empty text'),
        bpm_min=bpm_min, bpm_max=bpm_max, length=_length(document.get('length'), energy_plan),
        harmonic_mixing=enabled, minimum_key_strength=minimum_key_strength, energy_plan=energy_plan,
        mood_hold=_mood_hold(document.get('mood_hold')))


def _check_object(value, label, fields, prefix):
    if not isinstance(value, dict):
        raise PlaylistRecipeError(f'{label} must be a JSON object')
    for name in value:
        if name not in fields:
            raise PlaylistRecipeError(f'Unknown recipe field: {prefix}{name}')


def _check_format(document):
    if document.get('format') != FORMAT:
        raise PlaylistRecipeError(f'This is not a playlist recipe: its format must be "{FORMAT}"')
    version = document.get('version')
    if version != VERSION or isinstance(version, bool):
        raise PlaylistRecipeError(f'Recipe version {version} is not supported; only version {VERSION} can be read')


def _required(mapping, name, prefix=''):
    if name not in mapping:
        raise PlaylistRecipeError(f'Recipe needs {prefix}{name}')
    return mapping[name]


def _text(value, message):
    if not isinstance(value, str) or not value.strip():
        raise PlaylistRecipeError(message)
    return value


def _number(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise PlaylistRecipeError(f'{name} must be a finite number')
    return float(value)


def _bpm(bpm):
    _check_object(bpm, 'bpm', ('min', 'max'), 'bpm.')
    bpm_min = _number(_required(bpm, 'min', 'bpm.'), 'bpm.min')
    bpm_max = _number(_required(bpm, 'max', 'bpm.'), 'bpm.max')
    if bpm_min > bpm_max:
        raise PlaylistRecipeError('bpm.min must not be above bpm.max')
    return bpm_min, bpm_max


def _length_value(unit, value, name):
    if unit == 'tracks':
        if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= MAXIMUM_TRACKS:
            raise PlaylistRecipeError(f'{name} must be a whole number from 1 to {MAXIMUM_TRACKS}')
        return value
    minutes = _number(value, name)
    if not 0 < minutes <= MAXIMUM_MINUTES:
        raise PlaylistRecipeError(f'{name} must be above 0 and at most {MAXIMUM_MINUTES}')
    return minutes


def _unit_and_value(mapping, prefix, both_message):
    units = [unit for unit in LENGTH_UNITS if unit in mapping]
    if len(units) > 1:
        raise PlaylistRecipeError(both_message)
    return (units[0], _length_value(units[0], mapping[units[0]], prefix + units[0])) if units else None


def _length(length, energy_plan):
    arc_lengths = [arc.length for arc in energy_plan if arc.length is not None]
    if arc_lengths:
        return _arc_chain_length(length, energy_plan, arc_lengths)
    if length is None:
        raise PlaylistRecipeError('Recipe needs a length, or a length on every arc')
    if len(energy_plan) > 1:
        raise PlaylistRecipeError('Each arc in a chain needs a length')
    _check_object(length, 'length', LENGTH_UNITS, 'length.')
    playlist_length = _unit_and_value(length, 'length.', 'length is tracks or minutes, not both')
    if playlist_length is None:
        raise PlaylistRecipeError('Recipe needs a length, or a length on every arc')
    return playlist_length


def _arc_chain_length(length, energy_plan, arc_lengths):
    if length is not None:
        raise PlaylistRecipeError("When arcs have lengths they set the playlist's: leave the recipe's length out")
    if len(arc_lengths) < len(energy_plan):
        raise PlaylistRecipeError('Each arc in a chain needs a length')
    unit = arc_lengths[0][0]
    if any(arc_unit != unit for arc_unit, _value in arc_lengths):
        raise PlaylistRecipeError('Give every arc its length in the same unit: tracks or minutes')
    total = sum(value for _unit, value in arc_lengths)
    limit = MAXIMUM_TRACKS if unit == 'tracks' else MAXIMUM_MINUTES
    if total > limit:
        raise PlaylistRecipeError(f'The arcs add up to {total:g} {unit}; a playlist is at most {limit} {unit}')
    return None


def _harmonic_mixing(harmonic):
    _check_object(harmonic, 'harmonic_mixing', ('enabled', 'minimum_key_strength'), 'harmonic_mixing.')
    enabled = harmonic.get('enabled', True)
    if not isinstance(enabled, bool):
        raise PlaylistRecipeError('harmonic_mixing.enabled must be true or false')
    strength = _fraction(harmonic.get('minimum_key_strength', DEFAULT_MINIMUM_KEY_STRENGTH),
                         'harmonic_mixing.minimum_key_strength')
    return enabled, strength


def _fraction(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value <= 1:
        raise PlaylistRecipeError(f'{name} must be between 0 and 1')
    return float(value)


def _mood_hold(mood):
    if mood is not None and (not isinstance(mood, str) or not mood.strip()):
        raise PlaylistRecipeError('mood_hold must be non-empty text or null')
    return mood


def _energy_plan(arcs):
    if not isinstance(arcs, list):
        raise PlaylistRecipeError('energy_plan must be a list of arcs')
    return tuple(_arc(arc, f'energy_plan[{place}].') for place, arc in enumerate(arcs))


def _arc(arc, prefix):
    _check_object(arc, prefix.rstrip('.'), _ARC_FIELDS, prefix)
    shape = _required(arc, 'shape', prefix)
    if shape not in ARC_SHAPES:
        raise PlaylistRecipeError(f'{prefix}shape must be {", ".join(ARC_SHAPES[:-1])} or {ARC_SHAPES[-1]}')
    low, high = (_optional_arousal(arc.get(bound), prefix + bound) for bound in ('energy_low', 'energy_high'))
    if low is not None and high is not None and low >= high:
        raise PlaylistRecipeError(f'{prefix}energy_low must be below its energy_high')
    length = _unit_and_value(arc, prefix, 'Give every arc its length in the same unit: tracks or minutes')
    return EnergyArc(shape, length, low, high)


def _optional_arousal(value, name):
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise PlaylistRecipeError(f'{name} must be a number')
    return float(value)


def missing_start_track(start_track_id: str) -> str:
    """Why a saved recipe cannot be used once its start track has left the analysis database."""
    return f'Its start track {start_track_id} is not in the analysis database'
