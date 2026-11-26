"""The body of a hand-built playlist download (#277): exactly {"track_ids": [...]}, checked before the use case sees it."""
from music_explorer.application.use_cases.download_hand_built_playlist.download_hand_built_playlist import (
    DownloadHandBuiltPlaylistRequest, HandBuiltPlaylistRequestError,
)

HAND_BUILT_PLAYLIST_FILENAME = 'hand-built-playlist.m3u'
_SHAPE = 'Send the playlist as {"track_ids": [...]}'


def hand_built_playlist_request(body) -> DownloadHandBuiltPlaylistRequest:
    if not isinstance(body, dict) or set(body) != {'track_ids'} or not isinstance(body['track_ids'], list):
        raise HandBuiltPlaylistRequestError(_SHAPE)
    return DownloadHandBuiltPlaylistRequest(tuple(body['track_ids']))
