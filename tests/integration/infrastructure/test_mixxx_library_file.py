"""Issue #133: the export creates a new Mixxx 2.5 library file atomically and never touches an existing one."""
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from music_analyzer.domain.mixxx_library import MixxxExportError, MixxxKey, MixxxTrack, track_location
from music_analyzer.infrastructure.mixxx.library_file import SqliteMixxxLibraryFile

TRACKS = (
    MixxxTrack(track_location('/music/Synthetic/One.flac'), 1234, 'One', 'Artist', 'Album', 301.5, 124.0,
               MixxxKey(22, 'Am'), 'flac', 0xF8D200),
    MixxxTrack(track_location('/music/Synthetic/Two.mp3'), 99, '', '', '', 12.0, 0.0, MixxxKey(0, ''), 'mp3'),
)


class SqliteMixxxLibraryFileTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.folder = Path(temp.name)
        self.destination = self.folder / 'mixxxdb.sqlite'
        self.library_file = SqliteMixxxLibraryFile()

    def read(self, sql):
        database = sqlite3.connect(f'file:{self.destination}?mode=ro', uri=True)
        try:
            return database.execute(sql).fetchall()
        finally:
            database.close()

    def test_it_creates_mixxx_2_5_with_its_schema_version(self):
        self.library_file.create(str(self.destination), TRACKS)
        self.assertEqual([('mixxx.schema.last_used_version', '39'), ('mixxx.schema.min_compatible_version', '3'),
                          ('mixxx.schema.version', '39')],
                         self.read("SELECT name, value FROM settings WHERE name LIKE 'mixxx.schema.%' ORDER BY name"))
        self.assertEqual(20, self.read("SELECT count(*) FROM sqlite_master WHERE type='table' "
                                       "AND name NOT LIKE 'sqlite_%'")[0][0])

    def test_each_track_is_a_location_and_a_library_row(self):
        self.library_file.create(str(self.destination), TRACKS)
        rows = self.read('SELECT l.location, l.filename, l.directory, l.filesize, l.fs_deleted, l.needs_verification, '
                         'b.title, b.artist, b.album, b.duration, b.bpm, b.key, b.key_id, b.filetype, b.mixxx_deleted, '
                         'b.header_parsed, b.color FROM library b JOIN track_locations l ON l.id = b.location ORDER BY b.id')
        self.assertEqual([
            ('/music/Synthetic/One.flac', 'One.flac', '/music/Synthetic', 1234, 0, 0, 'One', 'Artist', 'Album', 301.5,
             124.0, 'Am', 22, 'flac', 0, 1, 0xF8D200),
            ('/music/Synthetic/Two.mp3', 'Two.mp3', '/music/Synthetic', 99, 0, 0, '', '', '', 12.0, 0.0, '', 0, 'mp3',
             0, 1, None),
        ], rows)

    def test_an_existing_file_is_refused_and_left_untouched(self):
        self.destination.write_bytes(b'not ours')
        self.assertTrue(self.library_file.occupied(str(self.destination)))
        with self.assertRaisesRegex(MixxxExportError, 'already exists'):
            self.library_file.create(str(self.destination), TRACKS)
        self.assertEqual(b'not ours', self.destination.read_bytes())
        self.assertEqual(['mixxxdb.sqlite'], os.listdir(self.folder))

    def test_a_failed_write_leaves_no_file_behind(self):
        with mock.patch('music_analyzer.infrastructure.mixxx.library_file.os.replace', side_effect=OSError('disk full')):
            with self.assertRaises(MixxxExportError):
                self.library_file.create(str(self.destination), TRACKS)
        self.assertEqual([], os.listdir(self.folder))

    def test_a_missing_folder_is_reported(self):
        with self.assertRaisesRegex(MixxxExportError, 'folder'):
            self.library_file.create(str(self.folder / 'absent' / 'mixxxdb.sqlite'), TRACKS)
        self.assertFalse(self.library_file.occupied(str(self.folder / 'absent' / 'mixxxdb.sqlite')))


if __name__ == '__main__':
    unittest.main()
