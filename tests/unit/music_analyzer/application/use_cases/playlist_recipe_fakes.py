"""An in-memory recipe store and an event recorder for the playlist recipe use cases (#139)."""
from music_analyzer.application.ports.playlist_recipes import StoredPlaylistRecipe
from music_analyzer.domain.playlist_recipe import parse_playlist_recipe

START = 'sha256:' + 'a' * 64


def recipe_document(**fields):
    return {'format': 'playlist-recipe', 'version': 1, 'start_track_id': START, 'bpm': {'min': 100, 'max': 130},
            'length': {'tracks': 12}, **fields}


def a_recipe(**fields):
    return parse_playlist_recipe(recipe_document(**fields))


class FakePlaylistRecipeStore:
    def __init__(self, tracks=(START,), recipes=()):
        self.tracks = set(tracks)
        self.recipes = {recipe.name: recipe for recipe in recipes}
        self.writes = []

    def has_track(self, track_id):
        return track_id in self.tracks

    def stored_recipe(self, name):
        return self.recipes.get(name)

    def stored_recipes(self):
        return tuple(self.recipes.values())

    def store_recipe(self, name, document, format_version):
        self.writes.append(('store', name))
        previous = self.recipes.get(name)
        self.recipes[name] = StoredPlaylistRecipe(name, document, format_version,
                                                  previous.created_at if previous else 'created', 'updated')

    def delete_recipe(self, name):
        self.writes.append(('delete', name))
        return self.recipes.pop(name, None) is not None


def stored(name, document, created_at='2026-11-01 10:00:00', updated_at='2026-11-02 10:00:00'):
    return StoredPlaylistRecipe(name, document, 1, created_at, updated_at)


class RecordingEventBus:
    def __init__(self):
        self.events = []

    def publish(self, event):
        self.events.append(event)
