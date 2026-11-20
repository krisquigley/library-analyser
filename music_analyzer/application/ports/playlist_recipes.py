"""Where the analyzer keeps saved playlist recipes (#139)."""
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class StoredPlaylistRecipe:
    """A stored row. `document` is the decoded recipe, or None when the stored text is not JSON."""
    name: str
    document: object
    format_version: int
    created_at: str
    updated_at: str


class PlaylistRecipeStore(Protocol):
    def has_track(self, track_id: str) -> bool: ...
    def stored_recipe(self, name: str) -> StoredPlaylistRecipe | None: ...
    def stored_recipes(self) -> tuple[StoredPlaylistRecipe, ...]: ...
    def store_recipe(self, name: str, document: dict, format_version: int) -> None: ...
    def delete_recipe(self, name: str) -> bool: ...
