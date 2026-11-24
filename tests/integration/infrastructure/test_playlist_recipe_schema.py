"""Issue #139: schema v11 adds the analyzer's playlist_recipes table, migrated from v10 and audited by integrity."""
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest

from music_analyzer.application.dto.analysis import AnalysisError
from music_analyzer.infrastructure.persistence.analysis import SQLiteAnalysisRepository
from music_analyzer.infrastructure.persistence.explorer_readonly import ReadOnlyExplorerSQLiteRepository as AnalyzerReader
from music_analyzer.infrastructure.persistence.integrity import SQLiteIntegrityScanner
from music_explorer.infrastructure.explorer_readonly import ReadOnlyExplorerSQLiteRepository as ExplorerReader
from tests.integration.infrastructure.integrity_d1_public_fixture import PUBLIC_TRACK_IDS, create_public_core_database

RECIPE_COLUMNS = [('name', 'TEXT', 1, 1), ('recipe_json', 'TEXT', 1, 0), ('format_version', 'INTEGER', 1, 0),
                  ('created_at', 'TEXT', 1, 0), ('updated_at', 'TEXT', 1, 0)]


def _columns(path):
    with closing(sqlite3.connect(path)) as db:
        return [(row[1], row[2], row[3], row[5]) for row in db.execute('PRAGMA table_info(playlist_recipes)')]


def _version(path):
    with closing(sqlite3.connect(path)) as db:
        return db.execute('PRAGMA user_version').fetchone()[0]


class PlaylistRecipeSchemaTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / 'analysis.sqlite'

    def test_a_new_database_has_an_empty_recipes_table(self):
        SQLiteAnalysisRepository(str(self.path))

        self.assertEqual(12, _version(self.path))
        self.assertEqual(RECIPE_COLUMNS, _columns(self.path))

    def test_a_v10_database_migrates_to_v11_and_keeps_its_tracks(self):
        create_public_core_database(self.path, 10)

        SQLiteAnalysisRepository(str(self.path))

        self.assertEqual(12, _version(self.path))
        self.assertEqual(RECIPE_COLUMNS, _columns(self.path))
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(sorted(PUBLIC_TRACK_IDS), sorted(row[0] for row in db.execute('SELECT id FROM tracks')))

    def test_the_table_refuses_a_recipe_without_a_name_or_with_no_format_version(self):
        SQLiteAnalysisRepository(str(self.path))
        with closing(sqlite3.connect(self.path)) as db:
            for row in ((None, '{}', 1), ('warm-up', '{}', 0), ('warm-up', None, 1)):
                with self.subTest(row=row), self.assertRaises(sqlite3.IntegrityError):
                    db.execute('INSERT INTO playlist_recipes(name,recipe_json,format_version) VALUES(?,?,?)', row)
            db.execute("INSERT INTO playlist_recipes(name,recipe_json,format_version) VALUES('warm-up','{}',1)")
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute("INSERT INTO playlist_recipes(name,recipe_json,format_version) VALUES('warm-up','{}',1)")

    def test_a_v11_database_without_the_recipes_table_is_refused(self):
        create_public_core_database(self.path, 10)
        with closing(sqlite3.connect(self.path)) as db:
            db.execute('PRAGMA user_version=11')

        with self.assertRaises(AnalysisError):
            SQLiteAnalysisRepository(str(self.path))

    def test_both_explorer_readers_read_a_v11_database(self):
        create_public_core_database(self.path, 11)

        for reader in (AnalyzerReader, ExplorerReader):
            with self.subTest(reader=reader.__module__):
                self.assertEqual(11, reader(str(self.path)).metadata()['schema_version'])


class PlaylistRecipeIntegrityTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / 'analysis.sqlite'

    def test_a_v11_database_passes_the_schema_audit(self):
        create_public_core_database(self.path, 11)

        result = SQLiteIntegrityScanner().scan(str(self.path))

        self.assertEqual((11, True, 'completed', []),
                         (result.schema_version, result.supported, result.stop_reason, [f.code for f in result.findings]))

    def test_a_v11_database_without_the_recipes_table_fails_the_schema_audit(self):
        create_public_core_database(self.path, 11)
        with closing(sqlite3.connect(self.path)) as db:
            db.execute('DROP TABLE playlist_recipes')

        result = SQLiteIntegrityScanner().scan(str(self.path))

        self.assertEqual(['schema_object_set_mismatch'], [f.code for f in result.findings])

    def test_a_v10_database_must_not_have_a_recipes_table(self):
        create_public_core_database(self.path, 10)
        with closing(sqlite3.connect(self.path)) as db:
            db.execute('CREATE TABLE playlist_recipes(name TEXT)')

        result = SQLiteIntegrityScanner().scan(str(self.path))

        self.assertEqual(['schema_object_set_mismatch'], [f.code for f in result.findings])

    def test_a_drifted_recipes_table_fails_the_column_audit(self):
        create_public_core_database(self.path, 11)
        with closing(sqlite3.connect(self.path)) as db:
            db.execute('DROP TABLE playlist_recipes')
            db.execute('CREATE TABLE playlist_recipes(name TEXT NOT NULL PRIMARY KEY, recipe_json TEXT, '
                       'format_version INTEGER NOT NULL CHECK(format_version >= 1), '
                       'created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)')

        result = SQLiteIntegrityScanner().scan(str(self.path))

        self.assertIn('schema_columns_mismatch', [f.code for f in result.findings])


if __name__ == '__main__':
    unittest.main()
