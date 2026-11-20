"""Stored playlist recipe rows (#139), audited against the analyzer's own recipe contract.

The analyzer checks a recipe before it saves one, so a row that fails here was changed outside the analyzer.
Findings are counted per kind; no recipe name or document ever leaves this module.
"""
import json

from music_analyzer.domain.playlist_recipe import PlaylistRecipeError, parse_playlist_recipe, playlist_recipe_name

OWNER = 'playlist_recipes'
CODES = ('recipe_json_invalid', 'recipe_contract_invalid', 'recipe_name_invalid', 'recipe_version_invalid')
_ROWS_SQL = ('SELECT name, recipe_json, typeof(recipe_json) AS recipe_kind, format_version, '
             'typeof(format_version) AS version_kind FROM playlist_recipes ORDER BY rowid')
_COLUMNS = ('name', 'recipe_json', 'recipe_kind', 'format_version', 'version_kind')


def scan_playlist_recipes(delivery):
    from music_analyzer.infrastructure.persistence.integrity import check, finding
    counts = {}
    delivery.recipe_findings = counts
    delivery.recipe_work = 0
    for name, recipe_json, recipe_kind, format_version, version_kind in delivery.rows(_ROWS_SQL, _COLUMNS):
        delivery.recipe_work += 1
        for code in _row_codes(name, recipe_json if recipe_kind == 'text' else None, format_version, version_kind):
            delivery.claim_group(OWNER, code)
            counts[code] = counts.get(code, 0) + 1
    return check(OWNER, 'completed', delivery.recipe_work, 'rows'), tuple(
        finding(OWNER, code, count) for code, count in counts.items())


def _row_codes(name, recipe_json, format_version, version_kind):
    codes = [] if _canonical_name(name) else ['recipe_name_invalid']
    document = _document(recipe_json)
    if document is None:
        return codes + ['recipe_json_invalid']
    try:
        parse_playlist_recipe(document)
    except PlaylistRecipeError:
        return codes + ['recipe_contract_invalid']
    if version_kind != 'integer' or format_version != document['version']:
        codes.append('recipe_version_invalid')
    return codes


def _canonical_name(name):
    try:
        return playlist_recipe_name(name) == name
    except PlaylistRecipeError:
        return False


def _document(recipe_json):
    if recipe_json is None:
        return None
    try:
        return json.loads(recipe_json)
    except (ValueError, RecursionError):
        return None
