// Listing the saved playlist recipes and loading one into the draft (#139).
// The Explorer only reads saved recipes; `music-analyzer playlist-recipe save` stores them.

import {playlistDraftOfRecipe} from '../../domain/playlist-recipe-document.js';
import {nextSavedRecipeState} from '../../domain/saved-playlist-recipes.js';
import {EVENT_BUS} from '../ports/event-bus.js';
import {SAVED_PLAYLIST_RECIPES} from '../ports/explorer-api.js';
import {PLAYLIST_DRAFT_SESSION} from '../ports/playlist-draft-session.js';
import {requirePort} from '../ports/port.js';
import {
  savedRecipeFailed, savedRecipeLoaded, savedRecipeLoading, savedRecipesListed, savedRecipesListing,
} from './saved-recipe-events.js';

export function createSavedRecipeLoad({explorerApi, playlistDraft, eventBus}) {
  requirePort(SAVED_PLAYLIST_RECIPES, explorerApi);
  requirePort(PLAYLIST_DRAFT_SESSION, playlistDraft);
  requirePort(EVENT_BUS, eventBus);
  let state = 'idle';

  function move(action, event) {
    state = nextSavedRecipeState(state, action);
    eventBus.publish(event);
  }

  async function settle(work) {
    try {
      move('succeed', await work());
    } catch (error) {
      move('fail', savedRecipeFailed(error?.message || String(error)));
    }
  }

  async function list() {
    move('list', savedRecipesListing());
    await settle(async () => savedRecipesListed(await explorerApi.listSavedPlaylistRecipes()));
  }

  async function load(name) {
    move('load', savedRecipeLoading(name));
    await settle(async () => {
      const saved = await explorerApi.loadSavedPlaylistRecipe(name);
      const {startTrackId, draft} = playlistDraftOfRecipe(saved.recipe);
      playlistDraft.write({draft});
      return savedRecipeLoaded({name: saved.name, startTrackId, draft});
    });
  }

  return Object.freeze({state: () => state, list, load});
}
