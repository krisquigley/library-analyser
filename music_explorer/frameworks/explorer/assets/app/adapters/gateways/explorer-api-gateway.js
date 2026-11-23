// The ExplorerApi port over fetch (#146). A refusal's JSON {error} body is read for its message (#149, #152, #155, #158).

import {playlistDownloadQuery, playlistPreviewQuery} from './playlist-download-query.js';
import {playlistPreviewFrom} from './playlist-preview-dto.js';
import {savedPlaylistRecipeFrom, savedPlaylistRecipesFrom} from './saved-playlist-recipe-dto.js';

const DEFAULT_PLAYLIST_FILENAME = 'library-graph-playlist.m3u';
const DEFAULT_PLAYLIST_TYPE = 'audio/x-mpegurl;charset=utf-8';
const MOOD_GRAPH_CONTRACT = 'v3';
// The track list shows 100 rows a page: an owner decision (UI100).
const TRACK_PAGE_SIZE = '100';
const HISTORY_ACTIONS = Object.freeze(['undo', 'reset']);

export function fetchExplorerApi(fetchResource) {
  return Object.freeze({
    async downloadPlaylist(recipe) {
      const response = await fetchResource(playlistDownloadQuery(recipe));
      const body = response.text ? await response.text() : '';
      if (!response.ok) throw new Error(refusalMessage(response, body, 'M3U download failed'));
      return {
        filename: filenameOf(header(response, 'content-disposition')) || DEFAULT_PLAYLIST_FILENAME,
        contents: body,
        contentType: header(response, 'content-type') || DEFAULT_PLAYLIST_TYPE,
        warning: header(response, 'X-Music-Explorer-Playlist-Warning') || '',
      };
    },
    async previewPlaylist(recipe) {
      return playlistPreviewFrom(await answer(await fetchResource(playlistPreviewQuery(recipe)), 'Playlist preview failed'));
    },
    async listSavedPlaylistRecipes() {
      return savedPlaylistRecipesFrom(await answer(await fetchResource('/api/playlist-recipes'), 'Saved recipe list failed'));
    },
    async loadSavedPlaylistRecipe(name) {
      const path = '/api/playlist-recipes/load?' + new URLSearchParams({name}).toString();
      return savedPlaylistRecipeFrom(await answer(await fetchResource(path), 'Saved recipe failed to load'));
    },
    async loadMoodGraph(mood) {
      const response = await fetchResource(moodGraphPath(mood));
      if (!response.ok) throw new Error(refusalMessage(response, await response.text(), 'Graph request failed'));
      return response.json();
    },
    async searchTracks({query, cursor}) {
      const response = await fetchResource(trackSearchPath(query, cursor));
      if (!response.ok) throw new Error(refusalMessage(response, await response.text(), 'Track search failed'));
      const page = await response.json();
      return {tracks: page.tracks || [], metadata: page.metadata || {}, nextCursor: page.next_cursor || null};
    },
    async chooseCurrentTrack({trackId, selectionToken, selectionEpoch, clientId}) {
      const body = JSON.stringify({track_id: trackId, selection_token: selectionToken, selection_epoch: selectionEpoch,
        selection_client_id: clientId});
      return answer(await fetchResource('/api/current', {method: 'POST', headers: {'Content-Type': 'application/json'}, body}),
        'Track selection failed');
    },
    async applyHistory(action) {
      if (!HISTORY_ACTIONS.includes(action)) throw new Error(`not a history action: ${action}`);
      return answer(await fetchResource(`/api/${action}`, {method: 'POST'}), 'History request failed');
    },
    async loadTrackDetail(trackId) {
      return answer(await fetchResource('/api/tracks/' + encodeURIComponent(trackId)), 'Track detail request failed');
    },
    async loadLibraryState() {
      return answer(await fetchResource('/api/state'), 'Library state request failed');
    },
  });
}

async function answer(response, fallback) {
  if (!response.ok) throw new Error(refusalMessage(response, await response.text(), fallback));
  return response.json();
}

function trackSearchPath(query, cursor) {
  const params = new URLSearchParams({limit: TRACK_PAGE_SIZE, order: 'title', query});
  if (cursor) params.set('cursor', cursor);
  return '/api/tracks/summary?' + params.toString();
}

function moodGraphPath(mood) {
  const params = new URLSearchParams();
  if (mood) params.set('mood', mood);
  params.set('contract', MOOD_GRAPH_CONTRACT);
  return '/api/mood-axis-graph?' + params.toString();
}

function header(response, name) {
  return response.headers?.get ? response.headers.get(name) || '' : '';
}

function filenameOf(disposition) {
  return (/filename="?([^";]+)"?/i.exec(disposition) || [])[1];
}

function refusalMessage(response, body, fallback) {
  if (!body) return fallback;
  if (!header(response, 'content-type').includes('application/json')) return body;
  try {
    const refusal = JSON.parse(body);
    return typeof refusal?.error === 'string' && refusal.error ? refusal.error : body;
  } catch {
    return body;
  }
}
