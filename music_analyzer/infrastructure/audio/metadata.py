"""Embedded audio metadata extraction at the infrastructure boundary."""
from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from music_analyzer.application.dto.catalogue import TrackMetadata

_MAX_TAG_VALUES = 100
_MAX_VALUE_CHARS = 4096
_MAX_TOTAL_CHARS = 256 * 1024
_BINARY_HINTS = ('apic', 'covr', 'metadata_block_picture', 'picture', 'artwork')
_LYRICS_HINTS = ('lyrics', 'unsyncedlyrics', 'synclyrics')
_COMMON_ALIASES = {
    'title': ('title', '\xa9nam', 'tit2'),
    'artist': ('artist', '\xa9art', 'tpe1'),
    'album': ('album', '\xa9alb', 'talb'),
    'album_artist': ('albumartist', 'album artist', 'aalbumartist', 'aart', '\xa9aart', 'tpe2'),
    'track_number': ('tracknumber', 'track number', 'trkn', 'trck'),
    'disc_number': ('discnumber', 'disc number', 'disk', 'tpos'),
    'date': ('date', 'year', '\xa9day', 'tdrc'),
    'genre': ('genre', '\xa9gen', 'tcon'),
    'composer': ('composer', '\xa9wrt', 'tcom'),
    'comment': ('comment', 'description', '\xa9cmt', 'comm'),
}


class MutagenMetadataReader:
    """Read bounded textual tags from supported audio containers using mutagen.

    Binary artwork, private frames and lyrics are reported as warnings instead of
    being persisted because they are unbounded/non-essential for the explorer's
    current track identity panel.
    """

    def read(self, location: str) -> TrackMetadata:
        try:
            from mutagen import File  # type: ignore
        except ImportError:
            return TrackMetadata(warnings=('mutagen unavailable; embedded metadata not extracted',))
        try:
            audio = File(location, easy=False)
        except Exception as error:  # mutagen raises format-specific exceptions
            return TrackMetadata(warnings=(f'metadata unreadable: {error}',))
        if audio is None or not getattr(audio, 'tags', None):
            return TrackMetadata()
        tags: dict[str, tuple[str, ...]] = {}
        warnings: list[str] = []
        total = 0
        for raw_key, raw_value in audio.tags.items():
            key = _clean_key(str(raw_key))
            folded = key.lower()
            if not key:
                continue
            if any(hint in folded for hint in _BINARY_HINTS):
                warnings.append(f'{key}: embedded artwork/binary metadata omitted')
                continue
            if any(hint in folded for hint in _LYRICS_HINTS):
                warnings.append(f'{key}: lyrics omitted pending explicit privacy/size policy')
                continue
            values = []
            for value in _flatten(raw_value):
                text = _clean_value(value)
                if text is None:
                    continue
                if len(text) > _MAX_VALUE_CHARS:
                    warnings.append(f'{key}: oversized value omitted')
                    continue
                total += len(key) + len(text)
                if total > _MAX_TOTAL_CHARS:
                    warnings.append('metadata: total textual tag budget reached')
                    break
                values.append(text)
                if len(values) >= _MAX_TAG_VALUES:
                    warnings.append(f'{key}: value count capped')
                    break
            if values:
                tags[key] = tuple(dict.fromkeys(values))
            if total > _MAX_TOTAL_CHARS:
                break
        common = []
        lower = {key.lower(): values for key, values in tags.items()}
        for field, aliases in _COMMON_ALIASES.items():
            collected = []
            for alias in aliases:
                collected.extend(lower.get(alias, ()))
            if collected:
                unique = tuple(dict.fromkeys(collected))
                common.append((field, unique[0] if len(unique) == 1 else unique))
        return TrackMetadata(tuple(common), tuple(sorted(tags.items())), tuple(dict.fromkeys(warnings)))


def _clean_key(value: str) -> str:
    return ' '.join(value.replace('\x00', '').strip().split())[:128]


def _clean_value(value) -> str | None:
    if isinstance(value, bytes):
        return None
    if (isinstance(value, tuple) and len(value) == 2
            and all(isinstance(part, int) and part >= 0 for part in value)):
        current, total = value
        text = f'{current}/{total}' if total else str(current)
    else:
        text = str(value).replace('\x00', '').strip()
    if not text:
        return None
    return ' '.join(text.split())


def _flatten(value) -> Iterable[object]:
    if isinstance(value, (str, bytes)):
        yield value
    elif isinstance(value, Iterable):
        for item in value:
            yield item
    else:
        text = getattr(value, 'text', None)
        if isinstance(text, Iterable) and not isinstance(text, (str, bytes)):
            yield from text
        else:
            yield value
