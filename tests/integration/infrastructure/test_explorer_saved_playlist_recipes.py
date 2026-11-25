"""Issue #139: the Explorer's read-only reader reads saved recipes, and finds none in a database older than v11."""
from contextlib import closing
import hashlib
from pathlib import Path
import sqlite3
import tempfile
import unittest

from music_analyzer.infrastructure.persistence.playlist_recipes import SQLitePlaylistRecipeStore
from music_explorer.application.ports.saved_playlist_recipes import SavedPlaylistRecipeRow
from music_explorer.infrastructure.explorer_readonly import ReadOnlyExplorerSQLiteRepository
from tests.integration.infrastructure.integrity_d1_public_fixture import create_public_core_database

DOCUMENT = {'format': 'playlist-recipe', 'version': 2, 'start_track_id': 'x', 'mood_hold': 'calm ☕'}


def _digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class ExplorerSavedPlaylistRecipesTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / 'analysis.sqlite'

    def test_saved_recipes_are_read_by_name_or_all_together_without_writing(self):
        create_public_core_database(self.path, 11)
        store = SQLitePlaylistRecipeStore(str(self.path))
        store.store_recipe('b', DOCUMENT, 1)
        store.store_recipe('a', DOCUMENT, 1)
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("INSERT INTO playlist_recipes(name,recipe_json,format_version) VALUES('broken','{oops',1)")
        before = _digest(self.path)
        reader = ReadOnlyExplorerSQLiteRepository(str(self.path))

        recipes = reader.saved_playlist_recipes()

        self.assertEqual(['a', 'b', 'broken'], [saved.name for saved in recipes])
        self.assertEqual((DOCUMENT, DOCUMENT, None), tuple(saved.document for saved in recipes))
        self.assertTrue(all(isinstance(saved, SavedPlaylistRecipeRow) and saved.updated_at for saved in recipes))
        self.assertEqual(('a', DOCUMENT), (reader.saved_playlist_recipe('a').name, reader.saved_playlist_recipe('a').document))
        self.assertIsNone(reader.saved_playlist_recipe('missing'))
        self.assertEqual(before, _digest(self.path))

    def test_a_database_older_than_v11_has_no_saved_recipes(self):
        create_public_core_database(self.path, 10)
        reader = ReadOnlyExplorerSQLiteRepository(str(self.path))

        self.assertEqual(((), None), (reader.saved_playlist_recipes(), reader.saved_playlist_recipe('a')))


if __name__ == '__main__':
    unittest.main()
