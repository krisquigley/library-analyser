"""The rules a hand-built playlist keeps (#277, #287): one to the most tracks, each named once by a sensible ID.

Its download and its preview both hold the listener's list to them.
"""
MAXIMUM_HAND_BUILT_TRACKS = 500
MAXIMUM_TRACK_ID_LENGTH = 256


class HandBuiltPlaylistError(ValueError):
    pass


def hand_built_track_ids(track_ids) -> tuple[str, ...]:
    """The listener's track IDs, in their order, once they keep the rules."""
    track_ids = tuple(track_ids)
    if not track_ids:
        raise HandBuiltPlaylistError('Add at least one track to the playlist')
    if len(track_ids) > MAXIMUM_HAND_BUILT_TRACKS:
        raise HandBuiltPlaylistError(f'A playlist holds at most {MAXIMUM_HAND_BUILT_TRACKS} tracks')
    if not all(_is_track_id(track_id) for track_id in track_ids):
        raise HandBuiltPlaylistError(f'A track ID must be text of 1 to {MAXIMUM_TRACK_ID_LENGTH} characters')
    if len(set(track_ids)) != len(track_ids):
        raise HandBuiltPlaylistError('The playlist names a track more than once')
    return track_ids


def _is_track_id(value):
    return isinstance(value, str) and 0 < len(value) <= MAXIMUM_TRACK_ID_LENGTH and '\x00' not in value
