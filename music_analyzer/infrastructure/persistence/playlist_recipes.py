"""Saved playlist recipes in the analysis database's playlist_recipes table (#139)."""
import json

from music_analyzer.application.ports.playlist_recipes import StoredPlaylistRecipe
from music_analyzer.infrastructure.persistence.analysis import SQLiteAnalysisRepository

_COLUMNS = 'name,recipe_json,format_version,created_at,updated_at'


class SQLitePlaylistRecipeStore(SQLiteAnalysisRepository):
    def has_track(self, track_id: str) -> bool:
        with self._read_transaction() as db:
            return db.execute('SELECT 1 FROM tracks WHERE id=?', (track_id,)).fetchone() is not None

    def stored_recipe(self, name: str) -> StoredPlaylistRecipe | None:
        with self._read_transaction() as db:
            row = db.execute(f'SELECT {_COLUMNS} FROM playlist_recipes WHERE name=?', (name,)).fetchone()
        return None if row is None else _stored(row)

    def stored_recipes(self) -> tuple[StoredPlaylistRecipe, ...]:
        with self._read_transaction() as db:
            rows = db.execute(f'SELECT {_COLUMNS} FROM playlist_recipes ORDER BY name').fetchall()
        return tuple(_stored(row) for row in rows)

    def store_recipe(self, name: str, document: dict, format_version: int) -> None:
        recipe_json = json.dumps(document, ensure_ascii=False, allow_nan=False, sort_keys=True)
        with self._transaction() as db:
            db.execute("""INSERT INTO playlist_recipes(name,recipe_json,format_version) VALUES(?,?,?)
                          ON CONFLICT(name) DO UPDATE SET recipe_json=excluded.recipe_json,
                          format_version=excluded.format_version, updated_at=CURRENT_TIMESTAMP""",
                       (name, recipe_json, format_version))

    def delete_recipe(self, name: str) -> bool:
        with self._transaction() as db:
            return db.execute('DELETE FROM playlist_recipes WHERE name=?', (name,)).rowcount == 1


def _stored(row) -> StoredPlaylistRecipe:
    name, recipe_json, format_version, created_at, updated_at = row
    return StoredPlaylistRecipe(name, _decoded(recipe_json), format_version, created_at, updated_at)


def _decoded(recipe_json):
    try:
        return json.loads(recipe_json)
    except (TypeError, ValueError):
        return None
