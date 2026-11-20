"""Delete a saved playlist recipe by name (#139)."""
from dataclasses import dataclass

from music_analyzer.application.ports.event_bus import EventBus
from music_analyzer.application.ports.playlist_recipes import PlaylistRecipeStore
from music_analyzer.domain.playlist_recipe import PlaylistRecipeError


@dataclass(frozen=True)
class PlaylistRecipeDeleted:
    name: str


class DeletePlaylistRecipe:
    def __init__(self, store: PlaylistRecipeStore, events: EventBus):
        self._store = store
        self._events = events

    def execute(self, name: str) -> None:
        if not self._store.delete_recipe(name):
            raise PlaylistRecipeError(f'No recipe named "{name}"')
        self._events.publish(PlaylistRecipeDeleted(name))
