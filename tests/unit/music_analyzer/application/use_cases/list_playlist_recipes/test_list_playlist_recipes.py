"""Issue #139: the saved recipes, by name, each with what would stop it loading."""
import unittest

from music_analyzer.application.use_cases.list_playlist_recipes import ListPlaylistRecipes, PlaylistRecipeSummary
from tests.unit.music_analyzer.application.use_cases.playlist_recipe_fakes import (
    START, FakePlaylistRecipeStore, recipe_document, stored)


class ListPlaylistRecipesTests(unittest.TestCase):
    def test_recipes_are_listed_by_name_with_their_start_track_and_any_problem(self):
        store = FakePlaylistRecipeStore(recipes=[
            stored('b gone', recipe_document(start_track_id='sha256:gone')),
            stored('a fine', recipe_document()),
            stored('c broken', {'format': 'playlist-recipe', 'version': 1}),
            stored('d unreadable', None),
        ])

        summaries = ListPlaylistRecipes(store).execute()

        self.assertEqual([
            PlaylistRecipeSummary('a fine', START, '2026-11-02 10:00:00', None),
            PlaylistRecipeSummary('b gone', 'sha256:gone', '2026-11-02 10:00:00',
                                  'Its start track sha256:gone is not in the analysis database'),
            PlaylistRecipeSummary('c broken', None, '2026-11-02 10:00:00', 'Recipe needs bpm'),
            PlaylistRecipeSummary('d unreadable', None, '2026-11-02 10:00:00', 'The recipe must be a JSON object'),
        ], list(summaries))

    def test_no_recipes(self):
        self.assertEqual((), ListPlaylistRecipes(FakePlaylistRecipeStore()).execute())


if __name__ == '__main__':
    unittest.main()
