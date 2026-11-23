"""The new Mixxx 2.5 library file the export creates (#133).

The destination is reserved with an exclusive create, so an existing file (a Mixxx database included) is
refused and never opened. The library is written to a temporary file beside it and moved over the
reservation only once complete, so a failed export leaves nothing behind. This works on filesystems without
hard links, such as a FAT-formatted USB drive.
"""
from __future__ import annotations

import contextlib
from importlib import resources
import os
from pathlib import Path
import sqlite3
import tempfile

from music_analyzer.domain.mixxx_library import MixxxExportError, MixxxTrack

SCHEMA_REVISION = 39
MIN_COMPATIBLE_REVISION = 3
_SCHEMA = resources.files('music_analyzer.infrastructure.mixxx').joinpath('data', 'mixxx-2.5-schema.sql')


class SqliteMixxxLibraryFile:
    def occupied(self, destination: str) -> bool:
        return os.path.lexists(destination)

    def create(self, destination: str, tracks: tuple[MixxxTrack, ...]) -> None:
        target = Path(destination)
        if not target.parent.is_dir():
            raise MixxxExportError(f'The folder {target.parent} does not exist: create it, or choose another')
        _reserve(target)
        try:
            _write_beside(target, tracks)
        except BaseException:
            target.unlink(missing_ok=True)
            raise


def _reserve(target):
    try:
        os.close(os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644))
    except FileExistsError:
        raise MixxxExportError(f'{target} already exists: the export only creates a new file') from None


def _write_beside(target, tracks):
    handle, temporary = tempfile.mkstemp(prefix='.' + target.name + '.', suffix='.partial', dir=target.parent)
    os.close(handle)
    try:
        _write_library(temporary, tracks)
        os.replace(temporary, target)
    except (OSError, sqlite3.Error) as error:
        raise MixxxExportError(f'Could not write {target}: {error}') from error
    finally:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(temporary)


def _write_library(path, tracks):
    database = sqlite3.connect(path)
    try:
        database.executescript(_SCHEMA.read_text(encoding='utf-8'))
        with database:
            _write_schema_version(database)
            for track in tracks:
                _write_track(database, track)
    finally:
        database.close()


def _write_schema_version(database):
    database.executemany('INSERT INTO settings (name, value) VALUES (?, ?)', [
        ('mixxx.schema.version', str(SCHEMA_REVISION)),
        ('mixxx.schema.last_used_version', str(SCHEMA_REVISION)),
        ('mixxx.schema.min_compatible_version', str(MIN_COMPATIBLE_REVISION)),
    ])


def _write_track(database, track):
    location = track.location
    location_id = database.execute(
        'INSERT INTO track_locations (location, filename, directory, filesize, fs_deleted, needs_verification) '
        'VALUES (?, ?, ?, ?, 0, 0)',
        (location.location, location.filename, location.directory, track.filesize)).lastrowid
    # header_parsed=1: the row already holds the file's tags, so Mixxx keeps our BPM and key rather than
    # re-reading them from the file over the listener's overrides.
    database.execute(
        'INSERT INTO library (location, title, artist, album, duration, bpm, key, key_id, filetype, color, '
        'mixxx_deleted, played, header_parsed) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0, 1)',
        (location_id, track.title, track.artist, track.album, track.duration, track.bpm, track.key.text,
         track.key.key_id, track.file_type, track.color))
