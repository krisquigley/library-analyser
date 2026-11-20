"""Issue #139: saving a recipe stores its canonical form and announces it."""
import unittest

from music_analyzer.application.use_cases.save_playlist_recipe import (
    PlaylistRecipeSaved, SavePlaylistRecipe, SavePlaylistRecipeRequest)
from music_analyzer.domain.playlist_recipe import PlaylistRecipeError
from tests.unit.music_analyzer.application.use_cases.playlist_recipe_fakes import (
    FakePlaylistRecipeStore, RecordingEventBus, a_recipe, recipe_document, stored)


class SavePlaylistRecipeTests(unittest.TestCase):
    def setUp(self):
        self.store, self.events = FakePlaylistRecipeStore(), RecordingEventBus()
        self.save = SavePlaylistRecipe(self.store, self.events)

    def test_a_new_recipe_is_stored_in_its_canonical_form_and_announced(self):
        recipe = a_recipe()

        self.save.execute(SavePlaylistRecipeRequest('Warm-up', recipe, replace=False))

        self.assertEqual(recipe.to_document(), self.store.recipes['Warm-up'].document)
        self.assertEqual(1, self.store.recipes['Warm-up'].format_version)
        self.assertEqual([PlaylistRecipeSaved('Warm-up', replaced=False)], self.events.events)

    def test_an_existing_name_is_kept_unless_replacing_is_asked_for(self):
        self.store.recipes['Warm-up'] = stored('Warm-up', recipe_document())

        with self.assertRaisesRegex(PlaylistRecipeError, 'A recipe named "Warm-up" already exists'):
            self.save.execute(SavePlaylistRecipeRequest('Warm-up', a_recipe(mood_hold='calm'), replace=False))

        self.assertEqual(([], []), (self.store.writes, self.events.events))

    def test_replacing_keeps_the_creation_time_and_says_it_replaced(self):
        self.store.recipes['Warm-up'] = stored('Warm-up', recipe_document())

        self.save.execute(SavePlaylistRecipeRequest('Warm-up', a_recipe(mood_hold='calm'), replace=True))

        self.assertEqual(('calm', '2026-11-01 10:00:00'),
                         (self.store.recipes['Warm-up'].document['mood_hold'], self.store.recipes['Warm-up'].created_at))
        self.assertEqual([PlaylistRecipeSaved('Warm-up', replaced=True)], self.events.events)

    def test_a_recipe_whose_start_track_is_not_in_the_database_is_refused(self):
        with self.assertRaisesRegex(PlaylistRecipeError, 'start track sha256:bbb is not in the analysis database'):
            self.save.execute(SavePlaylistRecipeRequest('Warm-up', a_recipe(start_track_id='sha256:bbb'), replace=False))

        self.assertEqual(([], []), (self.store.writes, self.events.events))


if __name__ == '__main__':
    unittest.main()
