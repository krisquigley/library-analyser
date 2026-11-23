"""Issue #133: the pinned Mixxx 2.5 schema (revision 39) the export creates, packaged with its notice."""
import sqlite3
import unittest
from importlib import resources

DATA = resources.files('music_analyzer.infrastructure.mixxx').joinpath('data')
TABLES = ['settings', 'track_locations', 'LibraryHashes', 'Playlists', 'PlaylistTracks', 'cues', 'crates',
          'crate_tracks', 'library', 'itunes_library', 'itunes_playlists', 'itunes_playlist_tracks', 'traktor_library',
          'traktor_playlists', 'traktor_playlist_tracks', 'rhythmbox_library', 'rhythmbox_playlists',
          'rhythmbox_playlist_tracks', 'track_analysis', 'directories']


class MixxxSchemaFixtureTests(unittest.TestCase):
    def setUp(self):
        self.sql = DATA.joinpath('mixxx-2.5-schema.sql').read_text(encoding='utf-8')
        self.database = sqlite3.connect(':memory:')
        self.addCleanup(self.database.close)
        self.database.executescript(self.sql)

    def test_it_creates_every_mixxx_table_in_order_and_its_indexes(self):
        tables = [row[0] for row in self.database.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY rowid")]
        self.assertEqual(TABLES, tables)
        self.assertEqual(4, self.database.execute("SELECT count(*) FROM sqlite_master WHERE type='index' "
                                                  "AND name NOT LIKE 'sqlite_%'").fetchone()[0])

    def test_the_columns_the_export_writes_exist(self):
        library = {row[1] for row in self.database.execute('PRAGMA table_info(library)')}
        self.assertLessEqual({'artist', 'title', 'album', 'location', 'duration', 'bpm', 'key', 'key_id', 'color',
                              'filetype', 'datetime_added', 'mixxx_deleted'}, library)
        self.assertEqual(48, len(library))
        locations = [row[1] for row in self.database.execute('PRAGMA table_info(track_locations)')]
        self.assertEqual(['id', 'location', 'filename', 'directory', 'filesize', 'fs_deleted', 'needs_verification'],
                         locations)

    def test_its_provenance_and_license_ship_beside_it(self):
        self.assertIn('-- Schema revision: 39 (min_compatible 3)', self.sql)
        self.assertIn('commit 3ebac449e7e5fe2a0186596657696e87ce8b0e56', self.sql)
        notice = DATA.joinpath('NOTICE').read_text(encoding='utf-8')
        self.assertIn('GPL-2.0-or-later', notice)
        self.assertIn('Mixxx 2.5.6', DATA.joinpath('LICENSE.mixxx').read_text(encoding='utf-8')[:200])


if __name__ == '__main__':
    unittest.main()
