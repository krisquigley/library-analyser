"""Issue #139: the analyzer stores playlist recipes in its own database, as decoded documents."""
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest

from music_analyzer.infrastructure.persistence.playlist_recipes import SQLitePlaylistRecipeStore
from tests.integration.infrastructure.integrity_d1_public_fixture import PUBLIC_TRACK_IDS, create_public_core_database

DOCUMENT = {'format': 'playlist-recipe', 'version': 1, 'start_track_id': 'x', 'bpm': {'min': 100.0, 'max': 120.0},
            'length': {'tracks': 10}, 'mood_hold': 'calm ☕'}


class SQLitePlaylistRecipeStoreTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / 'analysis.sqlite'
        create_public_core_database(self.path, 11)
        self.store = SQLitePlaylistRecipeStore(str(self.path))

    def test_a_stored_recipe_reads_back_as_the_same_document(self):
        self.store.store_recipe('Warm-up', DOCUMENT, 1)

        stored = self.store.stored_recipe('Warm-up')

        self.assertEqual(('Warm-up', DOCUMENT, 1), (stored.name, stored.document, stored.format_version))
        self.assertTrue(stored.created_at and stored.updated_at)
        self.assertIsNone(self.store.stored_recipe('Cool-down'))

    def test_storing_again_replaces_the_document_and_keeps_the_creation_time(self):
        self.store.store_recipe('Warm-up', DOCUMENT, 1)
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("UPDATE playlist_recipes SET created_at='2026-01-01 00:00:00', updated_at='2026-01-01 00:00:00'")

        self.store.store_recipe('Warm-up', {**DOCUMENT, 'mood_hold': None}, 1)

        stored = self.store.stored_recipe('Warm-up')
        self.assertEqual((None, '2026-01-01 00:00:00'), (stored.document['mood_hold'], stored.created_at))
        self.assertNotEqual('2026-01-01 00:00:00', stored.updated_at)
        self.assertEqual(['Warm-up'], [recipe.name for recipe in self.store.stored_recipes()])

    def test_every_recipe_is_listed_and_deleting_says_whether_one_was_there(self):
        for name in ('b', 'a'):
            self.store.store_recipe(name, DOCUMENT, 1)

        self.assertEqual({'a', 'b'}, {recipe.name for recipe in self.store.stored_recipes()})
        self.assertEqual((True, False), (self.store.delete_recipe('a'), self.store.delete_recipe('a')))
        self.assertEqual(['b'], [recipe.name for recipe in self.store.stored_recipes()])

    def test_stored_text_that_is_not_json_reads_as_no_document(self):
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("INSERT INTO playlist_recipes(name,recipe_json,format_version) VALUES('broken','{not json',1)")

        self.assertIsNone(self.store.stored_recipe('broken').document)

    def test_whether_a_track_is_in_the_database(self):
        self.assertEqual((True, False), (self.store.has_track(PUBLIC_TRACK_IDS[0]), self.store.has_track('sha256:none')))


if __name__ == '__main__':
    unittest.main()
