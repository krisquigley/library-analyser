"""BPM and key tags in MP3 (ID3) and FLAC (Vorbis comments) files, through mutagen (#132).

Only the owned fields change: ID3 TBPM and TKEY, or Vorbis BPM and INITIALKEY. mutagen rewrites the tag
area only, so other tags, pictures and the audio stay byte-for-byte. An ID3 tag keeps its version; an
untagged MP3 gains ID3v2.3, the version most players read. Each write goes to a copy beside the file,
which replaces the original only once complete, so a failure leaves the file as it was.
"""
from __future__ import annotations

import contextlib
import os
from pathlib import Path
import shutil
import tempfile

from mutagen import MutagenError
from mutagen.flac import FLAC
from mutagen.id3 import ID3, ID3NoHeaderError, TBPM, TKEY

from music_explorer.application.ports.track_tags import OwnedTags, TrackTagsError

_NEW_ID3_VERSION = 3


class MutagenTrackTags:
    def read_owned(self, location: str) -> OwnedTags:
        reader = _format_of(location)[0]
        try:
            return reader(location)
        except (OSError, MutagenError) as error:
            raise TrackTagsError(f'Cannot read the tags of {location}: {error}') from error

    def write_owned(self, location: str, tags: OwnedTags) -> None:
        writer = _format_of(location)[1]
        target = Path(location)
        try:
            handle, temporary = tempfile.mkstemp(prefix='.' + target.name + '.', suffix='.partial', dir=target.parent)
        except OSError as error:
            raise TrackTagsError(f'Cannot write the tags of {location}: {error}') from error
        os.close(handle)
        try:
            shutil.copy2(target, temporary)
            writer(temporary, tags)
            os.replace(temporary, target)
        except (OSError, MutagenError) as error:
            raise TrackTagsError(f'Cannot write the tags of {location}: {error}') from error
        finally:
            with contextlib.suppress(FileNotFoundError):
                os.unlink(temporary)


def _format_of(location):
    suffix = Path(location).suffix.lower()
    if suffix == '.mp3':
        return _read_mp3, _write_mp3
    if suffix == '.flac':
        return _read_flac, _write_flac
    raise TrackTagsError(f'{location}: only MP3 and FLAC tags can be written')


def _read_mp3(path):
    if not Path(path).is_file():
        raise FileNotFoundError(f'No such file: {path}')
    try:
        id3 = ID3(path)
    except ID3NoHeaderError:
        return OwnedTags()
    return OwnedTags(_first(id3.get('TBPM')), _first(id3.get('TKEY')))


def _write_mp3(path, tags):
    try:
        id3 = ID3(path)
        version = id3.version[1] if id3.version[1] in (3, 4) else _NEW_ID3_VERSION
    except ID3NoHeaderError:
        id3, version = ID3(), _NEW_ID3_VERSION
    if tags.bpm is not None:
        id3.setall('TBPM', [TBPM(encoding=3, text=[tags.bpm])])
    if tags.key is not None:
        id3.setall('TKEY', [TKEY(encoding=3, text=[tags.key])])
    id3.save(path, v2_version=version)


def _read_flac(path):
    flac = FLAC(path)
    comments = flac.tags or {}
    return OwnedTags(_first_comment(comments, 'BPM'), _first_comment(comments, 'INITIALKEY'))


def _write_flac(path, tags):
    flac = FLAC(path)
    if flac.tags is None:
        flac.add_tags()
    if tags.bpm is not None:
        flac['BPM'] = tags.bpm
    if tags.key is not None:
        flac['INITIALKEY'] = tags.key
    flac.save()


def _first(frame):
    return str(frame.text[0]) if frame is not None and frame.text else None


def _first_comment(comments, name):
    values = comments.get(name) if name in comments else None
    return str(values[0]) if values else None
