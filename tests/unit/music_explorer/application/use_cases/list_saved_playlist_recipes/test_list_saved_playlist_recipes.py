"""Issue #139: the Explorer lists saved recipes by name, saying which cannot be loaded and why."""
import unittest

from music_explorer.application.use_cases.list_saved_playlist_recipes import (
    ListSavedPlaylistRecipes, SavedPlaylistRecipeSummary)
from tests.unit.music_explorer.application.use_cases.saved_recipe_fakes import FakeSavedRecipes, recipe_document, row


class ListSavedPlaylistRecipesTests(unittest.TestCase):
    def test_recipes_by_name_with_any_reason_they_cannot_be_loaded(self):
        recipes = FakeSavedRecipes([row('c', None), row('b', recipe_document(start_track_id='sha256:gone')),
                                    row('a', recipe_document())])

        self.assertEqual((
            SavedPlaylistRecipeSummary('a', '2026-11-02 10:00:00', None),
            SavedPlaylistRecipeSummary('b', '2026-11-02 10:00:00',
                                       'Its start track sha256:gone is not an available track in the analysis database'),
            SavedPlaylistRecipeSummary('c', '2026-11-02 10:00:00', 'The recipe must be a JSON object'),
        ), ListSavedPlaylistRecipes(recipes).execute())

    def test_no_saved_recipes(self):
        self.assertEqual((), ListSavedPlaylistRecipes(FakeSavedRecipes()).execute())


if __name__ == '__main__':
    unittest.main()
