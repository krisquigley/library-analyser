"""Issue #139: one saved recipe, in the form `save` accepts back."""
import unittest

from music_analyzer.application.use_cases.show_playlist_recipe import SavedPlaylistRecipe, ShowPlaylistRecipe
from music_analyzer.domain.playlist_recipe import PlaylistRecipeError, parse_playlist_recipe
from tests.unit.music_analyzer.application.use_cases.playlist_recipe_fakes import (
    FakePlaylistRecipeStore, recipe_document, stored)


class ShowPlaylistRecipeTests(unittest.TestCase):
    def test_a_saved_recipe_with_its_times_and_whether_its_start_track_is_still_there(self):
        store = FakePlaylistRecipeStore(recipes=[stored('Warm-up', recipe_document())])

        shown = ShowPlaylistRecipe(store).execute('Warm-up')

        self.assertEqual(SavedPlaylistRecipe('Warm-up', parse_playlist_recipe(recipe_document()).to_document(),
                                             '2026-11-01 10:00:00', '2026-11-02 10:00:00', None), shown)

    def test_a_missing_start_track_is_reported_not_hidden(self):
        store = FakePlaylistRecipeStore(tracks=(), recipes=[stored('Warm-up', recipe_document())])

        self.assertIn('is not in the analysis database', ShowPlaylistRecipe(store).execute('Warm-up').problem)

    def test_an_unknown_or_invalid_recipe_is_an_error_naming_it(self):
        store = FakePlaylistRecipeStore(recipes=[stored('broken', {'format': 'm3u'})])
        for name, message in (('Warm-up', 'No recipe named "Warm-up"'),
                              ('broken', 'The saved recipe "broken" cannot be read: This is not a playlist recipe')):
            with self.subTest(name=name), self.assertRaisesRegex(PlaylistRecipeError, message):
                ShowPlaylistRecipe(store).execute(name)


if __name__ == '__main__':
    unittest.main()
