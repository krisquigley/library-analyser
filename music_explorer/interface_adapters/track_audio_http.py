"""The track-audio request and response over HTTP (#258): one named track, its media type, and the bytes asked for.

A seek bar asks for byte ranges; one inclusive range is served, never several.
"""
from music_explorer.application.use_cases.listen_to_track.listen_to_track import (
    ListenToTrackRequest, TrackAudioRequestError)

_MEDIA_TYPES = {'.mp3': 'audio/mpeg', '.flac': 'audio/flac', '.m4a': 'audio/mp4', '.mp4': 'audio/mp4',
                '.aac': 'audio/aac', '.ogg': 'audio/ogg', '.oga': 'audio/ogg', '.opus': 'audio/ogg',
                '.wav': 'audio/wav', '.aiff': 'audio/aiff', '.aif': 'audio/aiff', '.webm': 'audio/webm'}


class TrackAudioFormatError(ValueError):
    pass


class TrackAudioRangeError(ValueError):
    pass


def track_audio_request_from_query(values) -> ListenToTrackRequest:
    """A parsed query string (name -> list of values), as the server's parser gives it."""
    tracks = values.get('track', ())
    if len(tracks) != 1:
        raise TrackAudioRequestError('Name one track to listen to')
    return ListenToTrackRequest(tracks[0])


def audio_media_type(location: str) -> str:
    name = location.replace('\\', '/').rpartition('/')[2]
    media_type = _MEDIA_TYPES.get('.' + name.rpartition('.')[2].lower()) if '.' in name else None
    if media_type is None:
        raise TrackAudioFormatError('This audio format cannot be played in the browser')
    return media_type


def byte_range(header: str | None, size: int) -> tuple[int, int] | None:
    """The inclusive (first, last) bytes a Range header asks for, or None for the whole file."""
    if header is None:
        return None
    unit, _, span = header.strip().partition('=')
    first, dash, last = span.partition('-')
    if unit != 'bytes' or not dash or not all(part.isdigit() or part == '' for part in (first, last)) or first == last == '':
        raise TrackAudioRangeError('Unsatisfiable range')
    if first == '':
        suffix = int(last)
        if suffix == 0:
            raise TrackAudioRangeError('Unsatisfiable range')
        return max(size - suffix, 0), size - 1
    start, end = int(first), size - 1 if last == '' else min(int(last), size - 1)
    if start >= size or end < start:
        raise TrackAudioRangeError('Unsatisfiable range')
    return start, end
