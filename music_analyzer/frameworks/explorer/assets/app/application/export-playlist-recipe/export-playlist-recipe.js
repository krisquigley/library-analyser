// Exporting the drafted playlist as a recipe file (#139). The Explorer never saves recipes:
// the listener stores the file with `music-analyzer playlist-recipe save` (owner decision, #139).

import {playlistRecipeDocument} from '../../domain/playlist-recipe-document.js';
import {EVENT_BUS} from '../ports/event-bus.js';
import {PLAYLIST_DRAFT_SESSION} from '../ports/playlist-draft-session.js';
import {PLAYLIST_FILE} from '../ports/playlist-file.js';
import {requirePort} from '../ports/port.js';
import {playlistRecipeExportFailed, playlistRecipeExported} from './playlist-recipe-export-events.js';

const RECIPE_FILE = Object.freeze({filename: 'playlist-recipe.json', contentType: 'application/json'});

export function createPlaylistRecipeExport({playlistDraft, playlistFile, eventBus}) {
  requirePort(PLAYLIST_DRAFT_SESSION, playlistDraft);
  requirePort(PLAYLIST_FILE, playlistFile);
  requirePort(EVENT_BUS, eventBus);

  function exportRecipe(startTrackId) {
    try {
      const document = playlistRecipeDocument(playlistDraft.read().draft, startTrackId);
      playlistFile.save({...RECIPE_FILE, contents: JSON.stringify(document, null, 2) + '\n'});
      eventBus.publish(playlistRecipeExported(RECIPE_FILE.filename));
    } catch (error) {
      eventBus.publish(playlistRecipeExportFailed(error?.message || String(error)));
    }
  }

  return Object.freeze({exportRecipe});
}
