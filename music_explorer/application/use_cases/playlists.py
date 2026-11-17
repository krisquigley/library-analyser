"""Application use cases for read-only playlist generation."""
from collections import defaultdict
from math import isfinite

from music_explorer.application.dto.playlists import M3UPlaylist
from music_explorer.domain.harmonic_mixing import HarmonicMixing, usable_key
from music_explorer.domain.playlist_walk import (
    DurationGoal, TrackCountGoal, WalkTrack, by_relation_score, walk_playlist)

MAX_PLAYLIST_TRACKS = 1000
MAX_PLAYLIST_MINUTES = 1440


class GenerateBpmGraphM3UPlaylist:
    """Generate an M3U by walking the related-track graph from a start track."""

    def __init__(self, repository):
        self.repository = repository

    def execute(self, *, start_track_id: str, bpm_min, bpm_max, length=None, duration_minutes=None,
                harmonic_mixing: HarmonicMixing | None = HarmonicMixing()):
        start_track_id = str(start_track_id or '')
        bpm_min = _finite_bound(bpm_min, 'BPM minimum')
        bpm_max = _finite_bound(bpm_max, 'BPM maximum')
        if bpm_min > bpm_max:
            raise ValueError('bpm bounds must be ordered')
        goal = _goal(length, duration_minutes)
        if not start_track_id:
            raise ValueError('start track is required')

        graph = self.repository.mood_axis_graph_snapshot(mood=None, sparse_k=10)
        tracks = tuple(self.repository.playlist_export_tracks())
        candidates = {track.track_id: track for track in tracks if _eligible(track, bpm_min, bpm_max)}
        if start_track_id not in candidates:
            all_tracks = {track.track_id: track for track in tracks}
            if start_track_id in all_tracks:
                start = all_tracks[start_track_id]
                _assert_playable(start, is_start=True)
                if _bpm_overridden(start):
                    raise ValueError('start track has a manual BPM override; its detected BPM is not used')
                if not _bpm_in_range(start.bpm, bpm_min, bpm_max):
                    raise ValueError('start track BPM is outside requested range')
            raise ValueError('start track is not playable or available')
        walk_tracks = {track_id: _walk_track(track, harmonic_mixing) for track_id, track in candidates.items()}
        if not goal.admits(walk_tracks[start_track_id]):
            raise ValueError('start track has no verified duration for a duration playlist')

        edges = getattr(graph, 'edges', None) if graph is not None else None
        if edges is None:
            _status, edges = self.repository.current_graph_edges(None)
        related = defaultdict(list)
        for edge in edges or ():
            if edge.a in candidates and edge.b in candidates:
                related[edge.a].append((edge.b, float(edge.score)))
                related[edge.b].append((edge.a, float(edge.score)))

        walk = walk_playlist(start_track_id, walk_tracks, related, goal,
                             rank_transition=_harmonic_ranking(harmonic_mixing))
        warning = None if walk.complete else _shortfall(goal)
        content = '#EXTM3U\n' + ''.join(candidates[track_id].path + '\n' for track_id in walk.track_ids)
        return M3UPlaylist(content, walk.track_ids, warning)


GenerateBpmGraphM3U = GenerateBpmGraphM3UPlaylist


def _goal(length, duration_minutes):
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


def _track_cap(length):
    if not isinstance(length, int) or isinstance(length, bool) or length < 1 or length > MAX_PLAYLIST_TRACKS:
        raise ValueError(f'Playlist length must be positive and between 1 and {MAX_PLAYLIST_TRACKS}')
    return length


def _shortfall(goal):
    if isinstance(goal, DurationGoal):
        return 'Playlist is shorter than the requested duration: no longer walk was found through connected tracks'
    return 'Playlist is shorter than requested because traversal reached a dead end in the connected graph'


def _walk_track(track, harmonic_mixing):
    return WalkTrack(track.track_id, getattr(track, 'artist', '') or '', getattr(track, 'duration_seconds', None),
                     bpm=track.bpm, key=_key(track, harmonic_mixing))


# A manual key annotation wins over detection, so the detected key is not used (as for BPM, #120).
def _key(track, harmonic_mixing):
    if harmonic_mixing is None or 'key' in getattr(track, 'manual_overrides', ()):
        return None
    return usable_key(getattr(track, 'key', None), getattr(track, 'scale', None), getattr(track, 'key_strength', None),
                      minimum_strength=harmonic_mixing.minimum_key_strength)


def _harmonic_ranking(harmonic_mixing):
    if harmonic_mixing is None:
        return by_relation_score

    def rank(from_track, to_track, relation_score):
        return harmonic_mixing.transition_score(relation_score, from_track.key, to_track.key, from_track.bpm, to_track.bpm)
    return rank


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


def _bpm_in_range(value, bpm_min, bpm_max):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and isfinite(value) and bpm_min <= float(value) <= bpm_max


# A manual BPM annotation wins over detection, and is text, not a tempo:
# the track has no usable BPM, exactly as in the mood-axis graph.
def _bpm_overridden(track):
    return 'bpm' in getattr(track, 'manual_overrides', ())


def _eligible(track, bpm_min, bpm_max):
    try:
        _assert_playable(track)
    except ValueError:
        return False
    return not _bpm_overridden(track) and _bpm_in_range(track.bpm, bpm_min, bpm_max)


def _assert_playable(track, *, is_start=False):
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
