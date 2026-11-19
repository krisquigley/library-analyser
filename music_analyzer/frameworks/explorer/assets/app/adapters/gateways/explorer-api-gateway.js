// The ExplorerApi port over fetch (#146). A refusal's JSON {error} body is read for its message (#149, #152).

import {playlistDownloadQuery} from './playlist-download-query.js';

const DEFAULT_PLAYLIST_FILENAME = 'library-graph-playlist.m3u';
const DEFAULT_PLAYLIST_TYPE = 'audio/x-mpegurl;charset=utf-8';
const MOOD_GRAPH_CONTRACT = 'v3';

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
    async loadMoodGraph(mood) {
      const response = await fetchResource(moodGraphPath(mood));
      if (!response.ok) throw new Error(refusalMessage(response, await response.text(), 'Graph request failed'));
      return response.json();
    },
  });
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
