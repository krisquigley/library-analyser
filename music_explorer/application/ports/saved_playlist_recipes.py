"""Saved playlist recipes as the Explorer reads them (#139). The Explorer never writes them."""
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class SavedPlaylistRecipeRow:
    """A stored recipe. `document` is the decoded recipe, or None when the stored text is not JSON."""
    name: str
    document: object
    updated_at: str


class SavedPlaylistRecipes(Protocol):
    def saved_playlist_recipes(self) -> tuple[SavedPlaylistRecipeRow, ...]: ...
    def saved_playlist_recipe(self, name: str) -> SavedPlaylistRecipeRow | None: ...
    def contains_active_track(self, track_id: str) -> bool: ...
