"""In-memory stand-ins for the tag-write ports (#132): no files, database or network."""
from dataclasses import replace

from music_explorer.application.ports.taggable_tracks import TaggableTrack
from music_explorer.application.ports.track_tags import OwnedTags, TrackTagsError


def taggable(track_id, **values):
    defaults = dict(sha256='sha-' + track_id, location=f'/music/{track_id}.mp3', detected_bpm=124.0, tonic='A',
                    scale='minor', key_strength=0.9)
    return TaggableTrack(track_id, **{**defaults, **values})


class FakeTaggableTracks:
    def __init__(self, *tracks):
        self.tracks = {track.track_id: track for track in tracks}

    def read(self, track_id):
        return self.tracks.get(track_id)


class FakeTrackTags:
    def __init__(self, tags=None, unreadable=(), unwritable=()):
        self.tags = dict(tags or {})
        self.unreadable, self.unwritable = set(unreadable), set(unwritable)
        self.writes = []

    def read_owned(self, location):
        if location in self.unreadable:
            raise TrackTagsError(f'Cannot read the tags of {location}: synthetic failure')
        return self.tags.get(location, OwnedTags())

    def write_owned(self, location, tags):
        if location in self.unwritable:
            raise TrackTagsError(f'Cannot write the tags of {location}: synthetic failure')
        self.writes.append((location, tags))
        current = self.tags.get(location, OwnedTags())
        self.tags[location] = OwnedTags(tags.bpm if tags.bpm is not None else current.bpm,
                                        tags.key if tags.key is not None else current.key)


class FakeFileIdentity:
    def __init__(self, tracks, changed=()):
        self.identities = {track.location: track.sha256 for track in tracks.tracks.values()}
        for location in changed:
            self.identities[location] = 'changed'

    def sha256(self, location):
        return self.identities.get(location)


class FakeTagWriteActions:
    def __init__(self):
        self.actions, self.issued = {}, 0

    def new_token(self):
        self.issued += 1
        return f'token-{self.issued}'

    def save(self, action):
        self.actions[action.token] = action

    def find(self, token):
        return self.actions.get(token)


class FakeEvents:
    def __init__(self):
        self.published = []

    def publish(self, event):
        self.published.append(event)
