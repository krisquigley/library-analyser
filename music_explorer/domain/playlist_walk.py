"""Playlist walk over related tracks (#121).

A depth-first search that follows the best-ranked transitions first and
backtracks out of dead ends. By default a transition ranks by its relation
score; a ranking such as harmonic mixing (#122) can adjust that. Its first full playlist is therefore the greedy walk whenever
greedy succeeds. Work is bounded: after `expansion_limit` steps it returns the
longest walk found so far, marked incomplete.
"""
from dataclasses import dataclass
from math import isfinite
from typing import Mapping, Sequence

DEFAULT_EXPANSION_LIMIT = 20_000


@dataclass(frozen=True)
class WalkTrack:
    track_id: str
    artist: str = ''
    duration_seconds: float | None = None
    bpm: float | None = None
    key: object = None


@dataclass(frozen=True)
class TrackCountGoal:
    count: int

    @property
    def max_tracks(self):
        return self.count

    def admits(self, track):
        return True

    def progress(self, walk):
        return len(walk)

    def reached(self, walk):
        return len(walk) >= self.count


@dataclass(frozen=True)
class DurationGoal:
    seconds: float
    max_tracks: int

    def admits(self, track):
        duration = track.duration_seconds
        return isinstance(duration, (int, float)) and isfinite(duration) and duration > 0

    def progress(self, walk):
        return sum(track.duration_seconds for track in walk)

    def reached(self, walk):
        return self.progress(walk) >= self.seconds


@dataclass(frozen=True)
class PlaylistWalk:
    track_ids: tuple[str, ...]
    complete: bool


def by_relation_score(from_track, to_track, relation_score):
    return relation_score


def walk_playlist(start: str, tracks: Mapping[str, WalkTrack],
                  related: Mapping[str, Sequence[tuple[str, float]]], goal, *,
                  rank_transition=by_relation_score,
                  expansion_limit: int = DEFAULT_EXPANSION_LIMIT) -> PlaylistWalk:
    """Walk from `start` through `related` tracks until `goal` is reached."""
    strongest_first = {track_id: _best_first(tracks, track_id, neighbours, rank_transition)
                       for track_id, neighbours in related.items() if track_id in tracks}
    walk = [tracks[start]]
    on_walk = {start}
    longest = list(walk)
    choices = [iter(strongest_first.get(start, ()))]
    expansions = 0
    while choices:
        if goal.reached(walk):
            return PlaylistWalk(_ids(walk), True)
        if goal.progress(walk) > goal.progress(longest):
            longest = list(walk)
        following = None
        if len(walk) < goal.max_tracks and expansions < expansion_limit:
            following = next((tracks[n] for n in choices[-1]
                              if n in tracks and n not in on_walk and _may_follow(walk[-1], tracks[n], goal)), None)
        if following is None:
            choices.pop()
            on_walk.discard(walk.pop().track_id)
            continue
        expansions += 1
        walk.append(following)
        on_walk.add(following.track_id)
        choices.append(iter(strongest_first.get(following.track_id, ())))
    return PlaylistWalk(_ids(longest), False)


def _best_first(tracks, track_id, neighbours, rank_transition):
    ranked = [(-rank_transition(tracks[track_id], tracks[n], score), n) for n, score in neighbours if n in tracks]
    return [n for _, n in sorted(ranked)]


def _may_follow(previous, track, goal):
    return goal.admits(track) and not _same_known_artist(previous, track)


def _same_known_artist(a, b):
    first, second = _artist_key(a.artist), _artist_key(b.artist)
    return bool(first) and first == second


def _artist_key(artist):
    return ' '.join(str(artist or '').split()).casefold()


def _ids(walk):
    return tuple(track.track_id for track in walk)
