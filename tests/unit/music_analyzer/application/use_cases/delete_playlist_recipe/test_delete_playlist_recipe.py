"""Issue #139: deleting a recipe removes it by name and announces it."""
import unittest

from music_analyzer.application.use_cases.delete_playlist_recipe import DeletePlaylistRecipe, PlaylistRecipeDeleted
from music_analyzer.domain.playlist_recipe import PlaylistRecipeError
from tests.unit.music_analyzer.application.use_cases.playlist_recipe_fakes import (
    FakePlaylistRecipeStore, RecordingEventBus, recipe_document, stored)


class DeletePlaylistRecipeTests(unittest.TestCase):
    def test_a_saved_recipe_is_deleted_and_announced(self):
        store, events = FakePlaylistRecipeStore(recipes=[stored('Warm-up', recipe_document())]), RecordingEventBus()

        DeletePlaylistRecipe(store, events).execute('Warm-up')

        self.assertEqual(({}, [PlaylistRecipeDeleted('Warm-up')]), (store.recipes, events.events))

    def test_an_unknown_name_is_an_error_and_announces_nothing(self):
        store, events = FakePlaylistRecipeStore(), RecordingEventBus()

        with self.assertRaisesRegex(PlaylistRecipeError, 'No recipe named "Warm-up"'):
            DeletePlaylistRecipe(store, events).execute('Warm-up')

        self.assertEqual([], events.events)


if __name__ == '__main__':
    unittest.main()
