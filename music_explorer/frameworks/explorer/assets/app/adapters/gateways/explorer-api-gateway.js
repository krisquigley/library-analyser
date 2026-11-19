// The ExplorerApi port over fetch (#146).

import {playlistDownloadQuery} from './playlist-download-query.js';

const DEFAULT_PLAYLIST_FILENAME = 'library-graph-playlist.m3u';
const DEFAULT_PLAYLIST_TYPE = 'audio/x-mpegurl;charset=utf-8';

export function fetchExplorerApi(fetchResource) {
  return Object.freeze({
    async downloadPlaylist(recipe) {
      const response = await fetchResource(playlistDownloadQuery(recipe));
      const body = response.text ? await response.text() : '';
      if (!response.ok) throw new Error(refusalMessage(response, body));
      return {
        filename: filenameOf(header(response, 'content-disposition')) || DEFAULT_PLAYLIST_FILENAME,
        contents: body,
        contentType: header(response, 'content-type') || DEFAULT_PLAYLIST_TYPE,
        warning: header(response, 'X-Music-Explorer-Playlist-Warning') || '',
      };
    },
  });
}

function header(response, name) {
  return response.headers?.get ? response.headers.get(name) || '' : '';
}

function filenameOf(disposition) {
  return (/filename="?([^";]+)"?/i.exec(disposition) || [])[1];
}

function refusalMessage(response, body) {
  if (!body) return 'M3U download failed';
  if (!header(response, 'content-type').includes('application/json')) return body;
  try {
    const refusal = JSON.parse(body);
    return typeof refusal?.error === 'string' && refusal.error ? refusal.error : body;
  } catch {
    return body;
  }
}
