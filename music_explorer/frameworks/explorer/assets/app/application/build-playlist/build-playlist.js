// Building a playlist by hand from the graph's labels (#278). + adds a neighbour and chooses it as the next selection;
// every change is kept in this browser and published with the labels known so far, then again once the new tracks are
// labelled. A notice says what went wrong last, until the next change. The playlist downloads as an M3U (#277).

import {
  EMPTY_HAND_BUILT_PLAYLIST, HandBuiltPlaylistError, addNeighbour, handBuiltPlaylistOf, removeTrack,
} from '../../domain/hand-built-playlist.js';
import {nextPlaylistDownloadState} from '../../domain/playlist-download.js';
import {EVENT_BUS} from '../ports/event-bus.js';
import {HAND_BUILT_PLAYLIST_DOWNLOADS, TRACK_LABELS} from '../ports/explorer-api.js';
import {HAND_BUILT_PLAYLIST_STORE} from '../ports/hand-built-playlist-store.js';
import {PLAYLIST_FILE} from '../ports/playlist-file.js';
import {requirePort} from '../ports/port.js';
import {
  handBuiltPlaylistChanged, handBuiltPlaylistDownloadFailed, handBuiltPlaylistDownloadStarted, handBuiltPlaylistDownloaded,
  handBuiltPlaylistTrackChosen,
} from './hand-built-playlist-events.js';

const MOST_TRACKS_LABELLED_AT_ONCE = 100;
const NOT_KEPT = 'This browser could not keep the playlist; it will be lost when the page reloads';

export function createHandBuiltPlaylist({store, explorerApi, playlistFile, eventBus}) {
  requirePort(HAND_BUILT_PLAYLIST_STORE, store);
  requirePort(HAND_BUILT_PLAYLIST_DOWNLOADS, explorerApi);
  requirePort(TRACK_LABELS, explorerApi);
  requirePort(PLAYLIST_FILE, playlistFile);
  requirePort(EVENT_BUS, eventBus);
  let trackIds = EMPTY_HAND_BUILT_PLAYLIST;
  let notice = '';
  let downloadState = 'idle';
  const labels = new Map();
  const askedForLabels = new Set();

  function publishChange() {
    eventBus.publish(handBuiltPlaylistChanged({trackIds, notice,
      labels: trackIds.filter(trackId => labels.has(trackId)).map(trackId => labels.get(trackId))}));
  }

  async function labelNewTracks() {
    const unlabelled = trackIds.filter(trackId => !askedForLabels.has(trackId));
    if (!unlabelled.length) return;
    for (const trackId of unlabelled) askedForLabels.add(trackId);
    for (let first = 0; first < unlabelled.length; first += MOST_TRACKS_LABELLED_AT_ONCE) {
      try {
        const answered = await explorerApi.labelTracks(unlabelled.slice(first, first + MOST_TRACKS_LABELLED_AT_ONCE));
        for (const answer of answered) labels.set(answer.trackId, answer);
      } catch {
        // A track left unlabelled still plays its part in the playlist; the strip names it by its place.
      }
    }
    publishChange();
  }

  async function change(edited) {
    trackIds = edited;
    notice = keep(edited);
    publishChange();
    await labelNewTracks();
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
    await labelNewTracks();
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
    await labelNewTracks();
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
    restore, add, download,
    remove: trackId => change(removeTrack(trackIds, trackId)),
    clear: () => change(EMPTY_HAND_BUILT_PLAYLIST),
    trackIds: () => trackIds,
    downloadState: () => downloadState,
  });
}
