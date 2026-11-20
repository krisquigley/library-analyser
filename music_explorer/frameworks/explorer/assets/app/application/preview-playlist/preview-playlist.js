// Previewing the drafted playlist (#138): the tracks the M3U download would hold, walked by the same rule.
// Only the latest preview is shown; one it overtook is dropped when it answers.

import {playlistRecipeOf} from '../../domain/playlist-draft.js';
import {nextPlaylistPreviewState} from '../../domain/playlist-preview.js';
import {EVENT_BUS} from '../ports/event-bus.js';
import {PLAYLIST_PREVIEWS} from '../ports/explorer-api.js';
import {PLAYLIST_DRAFT_SESSION} from '../ports/playlist-draft-session.js';
import {requirePort} from '../ports/port.js';
import {playlistPreviewFailed, playlistPreviewStarted, playlistPreviewed} from './playlist-preview-events.js';

export function createPlaylistPreview({explorerApi, playlistDraft, eventBus}) {
  requirePort(PLAYLIST_PREVIEWS, explorerApi);
  requirePort(PLAYLIST_DRAFT_SESSION, playlistDraft);
  requirePort(EVENT_BUS, eventBus);
  let previewState = 'idle';
  let latest = 0;

  function settle(action, event) {
    previewState = nextPlaylistPreviewState(previewState, action);
    eventBus.publish(event);
  }

  async function preview(startTrackId) {
    const request = ++latest;
    settle('start', playlistPreviewStarted());
    try {
      const answer = await explorerApi.previewPlaylist(playlistRecipeOf(playlistDraft.read().draft, startTrackId));
      if (request === latest) settle('succeed', playlistPreviewed(answer));
    } catch (error) {
      if (request === latest) settle('fail', playlistPreviewFailed(error?.message || String(error)));
    }
  }

  return Object.freeze({previewState: () => previewState, preview});
}
