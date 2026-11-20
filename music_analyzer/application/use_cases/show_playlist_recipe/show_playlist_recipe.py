"""One saved playlist recipe, in the canonical form that saving accepts back (#139)."""
from dataclasses import dataclass

from music_analyzer.application.ports.playlist_recipes import PlaylistRecipeStore
from music_analyzer.domain.playlist_recipe import PlaylistRecipeError, missing_start_track, parse_playlist_recipe


@dataclass(frozen=True)
class SavedPlaylistRecipe:
    name: str
    document: dict
    created_at: str
    updated_at: str
    problem: str | None


class ShowPlaylistRecipe:
    def __init__(self, store: PlaylistRecipeStore):
        self._store = store

    def execute(self, name: str) -> SavedPlaylistRecipe:
        stored = self._store.stored_recipe(name)
        if stored is None:
            raise PlaylistRecipeError(f'No recipe named "{name}"')
        try:
            recipe = parse_playlist_recipe(stored.document)
        except PlaylistRecipeError as error:
            raise PlaylistRecipeError(f'The saved recipe "{name}" cannot be read: {error}') from error
        problem = None if self._store.has_track(recipe.start_track_id) else missing_start_track(recipe.start_track_id)
        return SavedPlaylistRecipe(name, recipe.to_document(), stored.created_at, stored.updated_at, problem)
