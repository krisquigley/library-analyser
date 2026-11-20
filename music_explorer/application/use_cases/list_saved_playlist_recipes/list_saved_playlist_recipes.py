"""The saved playlist recipes, by name, each with whatever stops it loading (#139)."""
from dataclasses import dataclass

from music_explorer.application.ports.saved_playlist_recipes import SavedPlaylistRecipeRow, SavedPlaylistRecipes
from music_explorer.domain.saved_playlist_recipe import (
    SavedPlaylistRecipeError, missing_start_track, parse_saved_playlist_recipe)


@dataclass(frozen=True)
class SavedPlaylistRecipeSummary:
    name: str
    updated_at: str
    problem: str | None


class ListSavedPlaylistRecipes:
    def __init__(self, recipes: SavedPlaylistRecipes):
        self._recipes = recipes

    def execute(self) -> tuple[SavedPlaylistRecipeSummary, ...]:
        rows = sorted(self._recipes.saved_playlist_recipes(), key=lambda saved: saved.name)
        return tuple(SavedPlaylistRecipeSummary(saved.name, saved.updated_at, self._problem(saved)) for saved in rows)

    def _problem(self, saved: SavedPlaylistRecipeRow) -> str | None:
        try:
            recipe = parse_saved_playlist_recipe(saved.document)
        except SavedPlaylistRecipeError as error:
            return str(error)
        return None if self._recipes.contains_active_track(recipe.start_track_id) else missing_start_track(recipe.start_track_id)
