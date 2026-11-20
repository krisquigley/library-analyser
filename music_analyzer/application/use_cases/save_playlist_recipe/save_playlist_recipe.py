"""Save a playlist recipe under a name (#139). The recipe arrives already checked against its format."""
from dataclasses import dataclass

from music_analyzer.application.ports.event_bus import EventBus
from music_analyzer.application.ports.playlist_recipes import PlaylistRecipeStore
from music_analyzer.domain.playlist_recipe import VERSION, PlaylistRecipe, PlaylistRecipeError


@dataclass(frozen=True)
class SavePlaylistRecipeRequest:
    name: str
    recipe: PlaylistRecipe
    replace: bool


@dataclass(frozen=True)
class PlaylistRecipeSaved:
    name: str
    replaced: bool


class SavePlaylistRecipe:
    def __init__(self, store: PlaylistRecipeStore, events: EventBus):
        self._store = store
        self._events = events

    def execute(self, request: SavePlaylistRecipeRequest) -> None:
        if not self._store.has_track(request.recipe.start_track_id):
            raise PlaylistRecipeError(f'The start track {request.recipe.start_track_id} is not in the analysis database')
        replaced = self._store.stored_recipe(request.name) is not None
        if replaced and not request.replace:
            raise PlaylistRecipeError(f'A recipe named "{request.name}" already exists: replace it, or choose another name')
        self._store.store_recipe(request.name, request.recipe.to_document(), VERSION)
        self._events.publish(PlaylistRecipeSaved(request.name, replaced))
