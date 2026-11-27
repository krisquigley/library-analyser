// Building a playlist by hand from the graph's labels (#278). + adds a neighbour and chooses it as the next selection,
// a track of the playlist can be chosen again from its table (#292) or moved a place earlier or later (#293);
// every change is kept in this browser and published with the last preview, then previewed (#287) and published again
// with its own. An answer overtaken by a later change is dropped. A notice says what went wrong last, until the next
// change. The playlist downloads as an M3U (#277).

import {
  EMPTY_HAND_BUILT_PLAYLIST, HandBuiltPlaylistError, addNeighbour, handBuiltPlaylistOf, moveTrack, removeTrack, trackOfPlaylist,
} from '../../domain/hand-built-playlist.js';
import {nextPlaylistDownloadState} from '../../domain/playlist-download.js';
import {EVENT_BUS} from '../ports/event-bus.js';
import {HAND_BUILT_PLAYLIST_DOWNLOADS, HAND_BUILT_PLAYLIST_PREVIEWS} from '../ports/explorer-api.js';
import {HAND_BUILT_PLAYLIST_STORE} from '../ports/hand-built-playlist-store.js';
import {PLAYLIST_FILE} from '../ports/playlist-file.js';
import {requirePort} from '../ports/port.js';
import {
  handBuiltPlaylistChanged, handBuiltPlaylistDownloadFailed, handBuiltPlaylistDownloadStarted, handBuiltPlaylistDownloaded,
  handBuiltPlaylistTrackChosen,
} from './hand-built-playlist-events.js';

const NOT_KEPT = 'This browser could not keep the playlist; it will be lost when the page reloads';

export function createHandBuiltPlaylist({store, explorerApi, playlistFile, eventBus}) {
  requirePort(HAND_BUILT_PLAYLIST_STORE, store);
  requirePort(HAND_BUILT_PLAYLIST_DOWNLOADS, explorerApi);
  requirePort(HAND_BUILT_PLAYLIST_PREVIEWS, explorerApi);
  requirePort(PLAYLIST_FILE, playlistFile);
  requirePort(EVENT_BUS, eventBus);
  let trackIds = EMPTY_HAND_BUILT_PLAYLIST;
  let notice = '';
  let downloadState = 'idle';
  let previewed = null;
  let previewsAsked = 0;

  function publishChange() {
    eventBus.publish(handBuiltPlaylistChanged({trackIds, notice, previewed}));
  }

  async function previewChange() {
    const asking = ++previewsAsked;
    const asked = trackIds;
    if (!asked.length) {
      previewed = null;
      return;
    }
    try {
      const preview = await explorerApi.previewHandBuiltPlaylist(asked);
      if (asking !== previewsAsked) return;
      previewed = {trackIds: asked, tracks: preview.tracks, transitions: preview.transitions};
    } catch (error) {
      if (asking !== previewsAsked) return;
      notice = `Could not show the playlist's details: ${error?.message || String(error)}`;
    }
    publishChange();
  }

  async function change(edited) {
    trackIds = edited;
    notice = keep(edited);
    if (!edited.length) previewed = null;
    publishChange();
    await previewChange();
  }

  function keep(edited) {
    try {
      store.save(edited);
      return '';
    } catch {
      return NOT_KEPT;
    }
  }

  async function restore() {
    try {
      trackIds = handBuiltPlaylistOf(store.load());
      notice = '';
    } catch (error) {
      trackIds = EMPTY_HAND_BUILT_PLAYLIST;
      notice = error instanceof HandBuiltPlaylistError ? error.message : NOT_KEPT;
    }
    publishChange();
    await previewChange();
  }

  async function add(choice) {
    let edited;
    try {
      edited = addNeighbour(trackIds, choice);
    } catch (error) {
      if (!(error instanceof HandBuiltPlaylistError)) throw error;
      notice = error.message;
      publishChange();
      return eventBus.publish(handBuiltPlaylistTrackChosen(choice.neighbourId));
    }
    if (edited === trackIds) return eventBus.publish(handBuiltPlaylistTrackChosen(choice.neighbourId));
    trackIds = edited;
    notice = keep(edited);
    publishChange();
    eventBus.publish(handBuiltPlaylistTrackChosen(choice.neighbourId));
    await previewChange();
  }

  async function move(trackId, places) {
    let edited;
    try {
      edited = moveTrack(trackIds, trackId, places);
    } catch (error) {
      if (!(error instanceof HandBuiltPlaylistError)) throw error;
      notice = error.message;
      return publishChange();
    }
    await change(edited);
  }

  async function download() {
    downloadState = nextPlaylistDownloadState(downloadState, 'start');
    eventBus.publish(handBuiltPlaylistDownloadStarted());
    try {
      playlistFile.save(await explorerApi.downloadHandBuiltPlaylist(trackIds));
      downloadState = nextPlaylistDownloadState(downloadState, 'succeed');
      eventBus.publish(handBuiltPlaylistDownloaded());
    } catch (error) {
      downloadState = nextPlaylistDownloadState(downloadState, 'fail');
      eventBus.publish(handBuiltPlaylistDownloadFailed(error?.message || String(error)));
    }
  }

  return Object.freeze({
    restore, add, move, download,
    choose: trackId => eventBus.publish(handBuiltPlaylistTrackChosen(trackOfPlaylist(trackIds, trackId))),
    remove: trackId => change(removeTrack(trackIds, trackId)),
    clear: () => change(EMPTY_HAND_BUILT_PLAYLIST),
    trackIds: () => trackIds,
    downloadState: () => downloadState,
  });
}
