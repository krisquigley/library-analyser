"""Load one saved playlist recipe for the playlist editor (#139), or say why it cannot be used."""
from dataclasses import dataclass

from music_explorer.application.ports.saved_playlist_recipes import SavedPlaylistRecipes
from music_explorer.domain.saved_playlist_recipe import (
    SavedPlaylistRecipeError, missing_start_track, parse_saved_playlist_recipe)


@dataclass(frozen=True)
class LoadedPlaylistRecipe:
    name: str
    recipe: dict


class LoadSavedPlaylistRecipe:
    def __init__(self, recipes: SavedPlaylistRecipes):
        self._recipes = recipes

    def execute(self, name: str) -> LoadedPlaylistRecipe:
        saved = self._recipes.saved_playlist_recipe(name)
        if saved is None:
            raise SavedPlaylistRecipeError(f'No saved recipe named "{name}"')
        try:
            recipe = parse_saved_playlist_recipe(saved.document)
        except SavedPlaylistRecipeError as error:
            raise SavedPlaylistRecipeError(f'The saved recipe "{name}" cannot be loaded: {error}') from error
        if not self._recipes.contains_active_track(recipe.start_track_id):
            raise SavedPlaylistRecipeError(
                f'The saved recipe "{name}" cannot be loaded: {missing_start_track(recipe.start_track_id)}')
        return LoadedPlaylistRecipe(name, recipe.to_document())
