"""The saved playlist recipes, by name, each with whatever would stop it being used (#139)."""
from dataclasses import dataclass

from music_analyzer.application.ports.playlist_recipes import PlaylistRecipeStore, StoredPlaylistRecipe
from music_analyzer.domain.playlist_recipe import PlaylistRecipeError, missing_start_track, parse_playlist_recipe


@dataclass(frozen=True)
class PlaylistRecipeSummary:
    name: str
    start_track_id: str | None
    updated_at: str
    problem: str | None


class ListPlaylistRecipes:
    def __init__(self, store: PlaylistRecipeStore):
        self._store = store

    def execute(self) -> tuple[PlaylistRecipeSummary, ...]:
        return tuple(self._summary(stored) for stored in sorted(self._store.stored_recipes(), key=lambda row: row.name))

    def _summary(self, stored: StoredPlaylistRecipe) -> PlaylistRecipeSummary:
        try:
            recipe = parse_playlist_recipe(stored.document)
        except PlaylistRecipeError as error:
            return PlaylistRecipeSummary(stored.name, None, stored.updated_at, str(error))
        problem = None if self._store.has_track(recipe.start_track_id) else missing_start_track(recipe.start_track_id)
        return PlaylistRecipeSummary(stored.name, recipe.start_track_id, stored.updated_at, problem)
