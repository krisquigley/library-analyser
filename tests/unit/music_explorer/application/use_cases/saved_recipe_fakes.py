"""An in-memory reader of saved playlist recipes for the Explorer's use cases (#139)."""
from music_explorer.application.ports.saved_playlist_recipes import SavedPlaylistRecipeRow

START = 'sha256:' + 'a' * 64


def recipe_document(**fields):
    return {'format': 'playlist-recipe', 'version': 2, 'start_track_id': START, 'bpm': {'min': 100, 'max': 130},
            'length': {'tracks': 12}, **fields}


def row(name, document, updated_at='2026-11-02 10:00:00'):
    return SavedPlaylistRecipeRow(name, document, updated_at)


class FakeSavedRecipes:
    def __init__(self, rows=(), active_tracks=(START,)):
        self.rows = {saved.name: saved for saved in rows}
        self.active_tracks = set(active_tracks)
        self.single_reads = []

    def saved_playlist_recipes(self):
        return tuple(self.rows.values())

    def saved_playlist_recipe(self, name):
        self.single_reads.append(name)
        return self.rows.get(name)

    def contains_active_track(self, track_id):
        return track_id in self.active_tracks
