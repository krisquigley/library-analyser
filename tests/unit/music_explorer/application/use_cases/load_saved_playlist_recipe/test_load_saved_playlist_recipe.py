"""Issue #139: loading a saved recipe gives its canonical form, or says clearly why it cannot be used."""
import unittest

from music_explorer.application.use_cases.load_saved_playlist_recipe import LoadSavedPlaylistRecipe, LoadedPlaylistRecipe
from music_explorer.domain.saved_playlist_recipe import SavedPlaylistRecipeError, parse_saved_playlist_recipe
from tests.unit.music_explorer.application.use_cases.saved_recipe_fakes import FakeSavedRecipes, recipe_document, row


class LoadSavedPlaylistRecipeTests(unittest.TestCase):
    def test_a_saved_recipe_loads_in_its_canonical_form_reading_only_that_row(self):
        recipes = FakeSavedRecipes([row('Warm-up', recipe_document()), row('other', None)])

        loaded = LoadSavedPlaylistRecipe(recipes).execute('Warm-up')

        self.assertEqual(LoadedPlaylistRecipe('Warm-up', parse_saved_playlist_recipe(recipe_document()).to_document()), loaded)
        self.assertEqual(['Warm-up'], recipes.single_reads)

    def test_what_stops_a_recipe_loading_is_named(self):
        recipes = FakeSavedRecipes([row('gone', recipe_document(start_track_id='sha256:gone')), row('broken', {'format': 1})])
        for name, message in (
                ('Nope', 'No saved recipe named "Nope"'),
                ('broken', 'The saved recipe "broken" cannot be loaded: This is not a playlist recipe'),
                ('gone', 'The saved recipe "gone" cannot be loaded: Its start track sha256:gone is not an available track')):
            with self.subTest(name=name), self.assertRaisesRegex(SavedPlaylistRecipeError, message):
                LoadSavedPlaylistRecipe(recipes).execute(name)


if __name__ == '__main__':
    unittest.main()
