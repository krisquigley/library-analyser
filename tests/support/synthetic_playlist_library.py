"""A seeded synthetic library for playlist-generation regression tests.

Every value is generated: no real titles, artists, paths or scores.
"""
from dataclasses import dataclass, field
import random

from music_explorer.application.dto.explorer import MoodAxisEdge
from music_explorer.application.dto.playlists import PlayableTrackCandidate, PlaylistMoodEvidence

_TONICS = ('C', 'C#', 'D', 'Eb', 'E', 'F', 'F#', 'G', 'Ab', 'A', 'Bb', 'B')


@dataclass(frozen=True)
class SyntheticPlaylistLibrary:
    tracks: tuple
    edges: tuple
    arousal: dict = field(default_factory=dict)
    calm: dict = field(default_factory=dict)

    def playlist_export_tracks(self):
        return self.tracks

    def related_track_edges(self, sparse_k):
        return {'state': 'ready'}, self.edges

    def playlist_mood_evidence(self, mood):
        return {track.track_id: PlaylistMoodEvidence(self.arousal.get(track.track_id),
                                                     self.calm.get(track.track_id) if mood == 'calm' else None)
                for track in self.tracks}


def synthetic_playlist_library(seed=135, size=80, neighbours=6):
    rng = random.Random(seed)
    tracks, arousal, calm = [], {}, {}
    for index in range(size):
        track_id = f't{index}'
        overrides = rng.choice(((),) * 12 + (('energy',), ('key',), ('mood',)))
        tracks.append(PlayableTrackCandidate(
            track_id, round(rng.uniform(115, 130), 1), f'/synthetic/{track_id}.flac',
            artist=f'artist {rng.randrange(20)}', manual_overrides=overrides,
            duration_seconds=round(rng.uniform(150, 420)), key=rng.choice(_TONICS),
            scale=rng.choice(('major', 'minor')), key_strength=round(rng.uniform(0.2, 1.0), 2)))
        if rng.random() > 0.1:
            arousal[track_id] = round(rng.uniform(2.5, 7.5), 3)
        if rng.random() > 0.2:
            calm[track_id] = round(rng.random(), 3)
    edges = {}
    for index in range(size):
        for other in rng.sample(range(size), neighbours):
            if other != index:
                a, b = sorted((f't{index}', f't{other}'))
                edges[(a, b)] = MoodAxisEdge(a, b, round(rng.uniform(0.75, 0.97), 3), 'synthetic', {}, 1)
    return SyntheticPlaylistLibrary(tuple(tracks), tuple(edges.values()), arousal, calm)
