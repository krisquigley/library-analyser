"""Application use cases for read-only playlist generation."""
from collections import defaultdict
from math import isfinite

from music_explorer.application.dto.playlists import M3UPlaylist


class GenerateBpmGraphM3UPlaylist:
    """Generate an M3U by greedily walking the related-track graph."""

    def __init__(self, repository):
        self.repository = repository

    def execute(self, *, start_track_id: str, bpm_min, bpm_max, length: int):
        start_track_id = str(start_track_id or '')
        bpm_min = _finite_bound(bpm_min, 'BPM minimum')
        bpm_max = _finite_bound(bpm_max, 'BPM maximum')
        if bpm_min > bpm_max:
            raise ValueError('bpm bounds must be ordered')
        if not isinstance(length, int) or isinstance(length, bool) or length < 1 or length > 1000:
            raise ValueError('Playlist length must be positive and between 1 and 1000')
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
                if not _bpm_in_range(start.bpm, bpm_min, bpm_max):
                    raise ValueError('start track BPM is outside requested range')
            raise ValueError('start track is not playable or available')

        edges = getattr(graph, 'edges', None) if graph is not None else None
        if edges is None:
            _status, edges = self.repository.current_graph_edges(None)
        adjacency = defaultdict(list)
        for edge in edges or ():
            if edge.a in candidates and edge.b in candidates:
                adjacency[edge.a].append((edge.b, float(edge.score)))
                adjacency[edge.b].append((edge.a, float(edge.score)))
        for track_id in adjacency:
            adjacency[track_id].sort(key=lambda item: (-item[1], item[0]))

        selected = [start_track_id]
        visited = {start_track_id}
        current = start_track_id
        while len(selected) < length:
            next_track = None
            for neighbour, _score in adjacency.get(current, ()):  # highest score, stable id tie
                if neighbour not in visited:
                    next_track = neighbour
                    break
            if next_track is None:
                break
            selected.append(next_track)
            visited.add(next_track)
            current = next_track

        warning = None
        if len(selected) < length:
            warning = 'Playlist is shorter than requested because traversal reached a dead end in the connected graph'
        content = '#EXTM3U\n' + ''.join(candidates[track_id].path + '\n' for track_id in selected)
        return M3UPlaylist(content, tuple(selected), warning)


GenerateBpmGraphM3U = GenerateBpmGraphM3UPlaylist


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


def _eligible(track, bpm_min, bpm_max):
    try:
        _assert_playable(track)
    except ValueError:
        return False
    return _bpm_in_range(track.bpm, bpm_min, bpm_max)


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
