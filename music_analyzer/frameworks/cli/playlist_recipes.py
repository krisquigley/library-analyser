"""`music-analyzer playlist-recipe save|list|show|delete` (#139): validated at this boundary, run by the use cases."""
import json
import sys

from music_analyzer.application.use_cases.delete_playlist_recipe import DeletePlaylistRecipe, PlaylistRecipeDeleted
from music_analyzer.application.use_cases.list_playlist_recipes import ListPlaylistRecipes
from music_analyzer.application.use_cases.save_playlist_recipe import (
    PlaylistRecipeSaved, SavePlaylistRecipe, SavePlaylistRecipeRequest)
from music_analyzer.application.use_cases.show_playlist_recipe import ShowPlaylistRecipe
from music_analyzer.domain.playlist_recipe import PlaylistRecipeError, parse_playlist_recipe, playlist_recipe_name
from music_analyzer.infrastructure.event_bus import InProcessEventBus
from music_analyzer.infrastructure.persistence.playlist_recipes import SQLitePlaylistRecipeStore
from music_analyzer.interface_adapters.presenters.playlist_recipes import (
    present_recipe_deleted, present_recipe_list, present_recipe_saved, present_saved_recipe)

MAXIMUM_RECIPE_FILE_BYTES = 1024 * 1024
COMMAND = 'playlist-recipe'


def add_playlist_recipe_commands(commands, add_configuration_options):
    recipes = commands.add_parser(COMMAND, help='Save, list, show or delete playlist recipes in the analysis database.')
    add_configuration_options(recipes)
    actions = recipes.add_subparsers(dest='recipe_action', required=True)
    save = actions.add_parser('save', help='Save a recipe JSON file under a name.')
    save.add_argument('--name', required=True, help='1 to 100 printable characters.')
    save.add_argument('--file', required=True, help='The recipe JSON, as the Explorer exports it or `show` prints it.')
    save.add_argument('--replace', action='store_true', help='Replace a saved recipe with the same name.')
    listing = actions.add_parser('list', help='List saved recipes and anything that stops one being used.')
    listing.add_argument('--json', action='store_true')
    for name, help_text in (('show', 'Print a saved recipe as JSON.'), ('delete', 'Delete a saved recipe.')):
        action = actions.add_parser(name, help=help_text)
        action.add_argument('name', metavar='NAME')
    for action in actions.choices.values():
        add_configuration_options(action)


def run_playlist_recipe_command(args, database: str) -> int:
    store, events = SQLitePlaylistRecipeStore(database), InProcessEventBus()
    events.subscribe(PlaylistRecipeSaved, lambda event: print(present_recipe_saved(event)))
    events.subscribe(PlaylistRecipeDeleted, lambda event: print(present_recipe_deleted(event)))
    if args.recipe_action == 'save':
        request = SavePlaylistRecipeRequest(playlist_recipe_name(args.name), parse_playlist_recipe(_recipe_file(args.file)),
                                            args.replace)
        SavePlaylistRecipe(store, events).execute(request)
    elif args.recipe_action == 'delete':
        DeletePlaylistRecipe(store, events).execute(playlist_recipe_name(args.name))
    elif args.recipe_action == 'list':
        print(present_recipe_list(ListPlaylistRecipes(store).execute(), args.json))
    else:
        _show(store, playlist_recipe_name(args.name))
    return 0


def _show(store, name):
    saved = ShowPlaylistRecipe(store).execute(name)
    print(present_saved_recipe(saved))
    if saved.problem:
        print(f'music-analyzer: warning: {saved.problem}', file=sys.stderr)


def _recipe_file(path: str):
    try:
        with open(path, 'rb') as recipe_file:
            content = recipe_file.read(MAXIMUM_RECIPE_FILE_BYTES + 1)
    except OSError as error:
        raise PlaylistRecipeError(f'cannot read the recipe file {path}: {error.strerror}') from error
    if len(content) > MAXIMUM_RECIPE_FILE_BYTES:
        raise PlaylistRecipeError(f'The recipe file {path} is larger than 1 MiB')
    try:
        return json.loads(content.decode('utf-8'))
    except (UnicodeDecodeError, ValueError) as error:
        raise PlaylistRecipeError(f'The recipe file {path} is not valid JSON: {error}') from error
