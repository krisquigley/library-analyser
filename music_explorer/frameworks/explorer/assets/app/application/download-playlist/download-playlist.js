// Drafting a playlist and downloading it as an M3U file (#146).

import {EMPTY_PLAYLIST_DRAFT, editPlaylistDraft, playlistRecipeOf} from '../../domain/playlist-draft.js';
import {nextPlaylistDownloadState} from '../../domain/playlist-download.js';
import {EVENT_BUS} from '../ports/event-bus.js';
import {PLAYLIST_DOWNLOADS} from '../ports/explorer-api.js';
import {PLAYLIST_FILE} from '../ports/playlist-file.js';
import {requirePort} from '../ports/port.js';
import {
  playlistDownloadFailed, playlistDownloadStarted, playlistDownloaded, playlistDraftEdited,
} from './playlist-download-events.js';

export function createPlaylistDownload({explorerApi, playlistFile, eventBus}) {
  requirePort(PLAYLIST_DOWNLOADS, explorerApi);
  requirePort(PLAYLIST_FILE, playlistFile);
  requirePort(EVENT_BUS, eventBus);
  let draft = EMPTY_PLAYLIST_DRAFT;
  let downloadState = 'idle';

  async function fetchAndSave(startTrackId) {
    const playlist = await explorerApi.downloadPlaylist(playlistRecipeOf(draft, startTrackId));
    playlistFile.save(playlist);
    return playlist;
  }

  return Object.freeze({
    draft: () => draft,
    downloadState: () => downloadState,
    edit(changes) {
      draft = editPlaylistDraft(draft, changes);
      eventBus.publish(playlistDraftEdited(draft));
    },
    async download(startTrackId) {
      downloadState = nextPlaylistDownloadState(downloadState, 'start');
      eventBus.publish(playlistDownloadStarted());
      try {
        const playlist = await fetchAndSave(startTrackId);
        downloadState = nextPlaylistDownloadState(downloadState, 'succeed');
        eventBus.publish(playlistDownloaded(playlist));
      } catch (error) {
        downloadState = nextPlaylistDownloadState(downloadState, 'fail');
        eventBus.publish(playlistDownloadFailed(error?.message || String(error)));
      }
    },
  });
}
