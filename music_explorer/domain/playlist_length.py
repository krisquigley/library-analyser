"""How long a playlist is (#58, #121, #137).

A playlist lasts a number of tracks or a duration in minutes. When its energy
arcs have lengths, it lasts their sum, all in one unit; a single arc without a
length spans the whole playlist.
"""
from math import isfinite

from music_explorer.domain.playlist_walk import DurationGoal, TrackCountGoal

MAX_PLAYLIST_TRACKS = 1000
MAX_PLAYLIST_MINUTES = 1440


def playlist_goal(length, duration_minutes):
    if duration_minutes is not None:
        try:
            minutes = float(duration_minutes)
        except (TypeError, ValueError):
            raise ValueError('Playlist duration must be a number of minutes')
        if not isfinite(minutes) or minutes <= 0 or minutes > MAX_PLAYLIST_MINUTES:
            raise ValueError(f'Playlist duration must be positive and at most {MAX_PLAYLIST_MINUTES} minutes')
        return DurationGoal(minutes * 60.0, _track_cap(MAX_PLAYLIST_TRACKS if length is None else length))
    if length is None:
        raise ValueError('Playlist length or duration is required')
    return TrackCountGoal(_track_cap(length))


def goal_and_arc_lengths(arcs, length, duration_minutes):
    """The playlist's goal, and each arc's length in the plan's unit (tracks, or seconds by duration).

    Each arc has `tracks` or `minutes`, or neither.
    """
    measured = [arc for arc in arcs if arc.tracks is not None or arc.minutes is not None]
    if not measured:
        if len(arcs) > 1:
            raise ValueError('Each arc in a chain needs a length')
        goal = playlist_goal(length, duration_minutes)
        return goal, (_playlist_span(goal),) * len(arcs)
    if len(measured) < len(arcs):
        raise ValueError('Each arc in a chain needs a length')
    if length is not None or duration_minutes is not None:
        raise ValueError("With arc lengths, the playlist's length is the sum of its arcs: leave its length unset")
    by_tracks = {arc.minutes is None for arc in arcs}
    if len(by_tracks) > 1 or any(arc.tracks is not None and arc.minutes is not None for arc in arcs):
        raise ValueError('Every arc must be measured in the same unit: tracks or minutes')
    if by_tracks == {True}:
        lengths = tuple(_arc_tracks(arc.tracks) for arc in arcs)
        return playlist_goal(sum(lengths), None), lengths
    minutes = tuple(_arc_minutes(arc.minutes) for arc in arcs)
    return playlist_goal(None, sum(minutes)), tuple(each * 60.0 for each in minutes)


def shortfall_warning(goal):
    if isinstance(goal, DurationGoal):
        return 'Playlist is shorter than the requested duration: no longer walk was found through connected tracks'
    return 'Playlist is shorter than requested because traversal reached a dead end in the connected graph'


def _playlist_span(goal):
    return goal.seconds if isinstance(goal, DurationGoal) else goal.count


def _track_cap(length):
    if not isinstance(length, int) or isinstance(length, bool) or length < 1 or length > MAX_PLAYLIST_TRACKS:
        raise ValueError(f'Playlist length must be positive and between 1 and {MAX_PLAYLIST_TRACKS}')
    return length


def _arc_tracks(value):
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ValueError('An arc length must be a whole number of tracks, at least 1')
    return value


def _arc_minutes(value):
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not isfinite(value) or value <= 0:
        raise ValueError('An arc length must be a positive number of minutes')
    return float(value)
