"""Translate the M3U download's query string into a PlaylistRecipe (#135, #137).

The query is `parse_qs` output, blanks kept: each name maps to a list of
values. A single value is the first one, and a blank one counts as left out.
Arcs repeat in order (#137): `arc` names each shape, and `energy_low`,
`energy_high` and `arc_tracks` or `arc_minutes`, when given, hold one value
per arc at the same place, blank for unset. Shapes, ranges and lengths are
validated by the use case and the domain; this adapter rejects only what
cannot be read at all.
"""
from typing import Mapping, Sequence

from music_explorer.application.dto.playlists import EnergyArcRequest, PlaylistRecipe
from music_explorer.domain.harmonic_mixing import DEFAULT_MINIMUM_KEY_STRENGTH

Query = Mapping[str, Sequence[str]]


def playlist_recipe_from_query(query: Query) -> PlaylistRecipe:
    duration_minutes = _first(query, 'duration_minutes')
    harmonic_mixing = _harmonic_mixing(query)
    energy_plan = _energy_plan(query)
    arcs_set_the_length = any(arc.tracks is not None or arc.minutes is not None for arc in energy_plan)
    return PlaylistRecipe(
        start_track_id=_first(query, 'start_track_id', _first(query, 'start', '')),
        bpm_min=_first(query, 'bpm_min'),
        bpm_max=_first(query, 'bpm_max'),
        length=_length(query, duration_minutes, arcs_set_the_length),
        duration_minutes=duration_minutes,
        harmonic_mixing=harmonic_mixing,
        minimum_key_strength=_minimum_key_strength(query) if harmonic_mixing else DEFAULT_MINIMUM_KEY_STRENGTH,
        energy_plan=energy_plan,
        mood_hold=_first(query, 'mood') or None,
    )


def _first(query, name, default=None):
    value = query.get(name, [None])[0]
    return default if value is None or not value.strip() else value


def _length(query, duration_minutes, arcs_set_the_length):
    # A duration playlist, or one whose arcs have lengths, needs no track count; a
    # track count playlist without one asks for 0 tracks, which the use case
    # rejects with its own message.
    default = None if duration_minutes is not None or arcs_set_the_length else '0'
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
    """No energy arc (#123) unless `arc` names a shape; `none` is the default."""
    shapes = [shape.strip() for shape in query.get('arc', [])]
    arcs = shapes if any(shape not in ('', 'none') for shape in shapes) else []
    lists = {name: _per_arc(query, name, len(arcs)) for name in _PER_ARC}
    if not arcs:
        if any(value for name in _RANGE for value in lists[name]):
            raise ValueError('An energy range needs an energy arc')
        if any(value for name in _LENGTH for value in lists[name]):
            raise ValueError('An arc length needs an energy arc')
        return ()
    if any(shape in ('', 'none') for shape in arcs):
        raise ValueError('Each arc in a chain needs a shape')
    return tuple(EnergyArcRequest(shape,
                                  energy_low=_energy_level(lists['energy_low'][index]),
                                  energy_high=_energy_level(lists['energy_high'][index]),
                                  tracks=_arc_tracks(lists['arc_tracks'][index]),
                                  minutes=_arc_minutes(lists['arc_minutes'][index]))
                 for index, shape in enumerate(arcs))


_RANGE = ('energy_low', 'energy_high')
_LENGTH = ('arc_tracks', 'arc_minutes')
_PER_ARC = _RANGE + _LENGTH


def _per_arc(query, name, arc_count):
    """One value per arc, blank when unset; a list that is left out is unset for every arc."""
    values = [value.strip() for value in query.get(name, [])]
    if not values:
        return [''] * max(arc_count, 1)
    if arc_count and len(values) != arc_count:
        raise ValueError(f'Give each arc its own {name}, in order: {arc_count} values, not {len(values)}')
    return values


def _energy_level(raw):
    try:
        return float(raw) if raw else None
    except ValueError:
        raise ValueError('Energy low and high must be between 0.0 and 1.0')


def _arc_tracks(raw):
    try:
        return int(raw) if raw else None
    except ValueError:
        raise ValueError('An arc length must be a whole number of tracks, at least 1')


def _arc_minutes(raw):
    try:
        return float(raw) if raw else None
    except ValueError:
        raise ValueError('An arc length must be a positive number of minutes')
