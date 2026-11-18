"""Translate the M3U download's query string into a PlaylistRecipe (#135).

The query is `parse_qs` output: each name maps to a list of values, of which
the first is used. Shapes and ranges are validated by the use case and the
domain; this adapter rejects only what cannot be read at all.
"""
from typing import Mapping, Sequence

from music_explorer.application.dto.playlists import EnergyArcRequest, PlaylistRecipe
from music_explorer.domain.harmonic_mixing import DEFAULT_MINIMUM_KEY_STRENGTH

Query = Mapping[str, Sequence[str]]


def playlist_recipe_from_query(query: Query) -> PlaylistRecipe:
    duration_minutes = _first(query, 'duration_minutes')
    harmonic_mixing = _harmonic_mixing(query)
    return PlaylistRecipe(
        start_track_id=_first(query, 'start_track_id', _first(query, 'start', '')),
        bpm_min=_first(query, 'bpm_min'),
        bpm_max=_first(query, 'bpm_max'),
        length=_length(query, duration_minutes),
        duration_minutes=duration_minutes,
        harmonic_mixing=harmonic_mixing,
        minimum_key_strength=_minimum_key_strength(query) if harmonic_mixing else DEFAULT_MINIMUM_KEY_STRENGTH,
        energy_plan=_energy_plan(query),
        mood_hold=_first(query, 'mood') or None,
    )


def _first(query, name, default=None):
    return query.get(name, [default])[0]


def _length(query, duration_minutes):
    # A duration playlist needs no track count; a track count playlist without
    # one asks for 0 tracks, which the use case rejects with its own message.
    default = None if duration_minutes is not None else '0'
    raw_length = _first(query, 'length', _first(query, 'count', default))
    try:
        return None if raw_length is None else int(raw_length)
    except ValueError:
        raise ValueError('Playlist length must be positive and between 1 and 1000')


def _harmonic_mixing(query):
    """Harmonic mixing (#122) is on unless `harmonic=off`."""
    switch = _first(query, 'harmonic', 'on')
    if switch not in ('on', 'off'):
        raise ValueError('Harmonic mixing must be on or off')
    return switch == 'on'


def _minimum_key_strength(query):
    raw_strength = _first(query, 'min_key_strength')
    try:
        return DEFAULT_MINIMUM_KEY_STRENGTH if raw_strength is None else float(raw_strength)
    except ValueError:
        raise ValueError('Minimum key strength must be between 0.0 and 1.0')


def _energy_plan(query):
    """No energy arc (#123) unless `arc` names a shape; `none` is the default.

    `energy_low` and `energy_high` (#136) set the arc's range; blank is unset.
    """
    shape = _first(query, 'arc', 'none')
    low, high = _energy_level(query, 'energy_low'), _energy_level(query, 'energy_high')
    if shape in ('', 'none'):
        if low is not None or high is not None:
            raise ValueError('An energy range needs an energy arc')
        return ()
    return (EnergyArcRequest(shape, energy_low=low, energy_high=high),)


def _energy_level(query, name):
    raw = (_first(query, name) or '').strip()
    try:
        return float(raw) if raw else None
    except ValueError:
        raise ValueError('Energy low and high must be between 0.0 and 1.0')
