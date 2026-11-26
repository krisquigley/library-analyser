"""The body of a hand-built playlist's download (#277) or preview (#287): exactly {"track_ids": [...]}, checked before
either use case sees it; the IDs themselves are held to the playlist's rules by the domain."""
from music_explorer.domain.hand_built_playlist import HandBuiltPlaylistError

HAND_BUILT_PLAYLIST_FILENAME = 'hand-built-playlist.m3u'
_SHAPE = 'Send the playlist as {"track_ids": [...]}'


def hand_built_track_ids_from_body(body) -> tuple:
    if not isinstance(body, dict) or set(body) != {'track_ids'} or not isinstance(body['track_ids'], list):
        raise HandBuiltPlaylistError(_SHAPE)
    return tuple(body['track_ids'])
