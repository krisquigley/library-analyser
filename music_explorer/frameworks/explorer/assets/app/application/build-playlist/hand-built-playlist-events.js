// What happens while the listener builds a playlist by hand from the graph's labels (#278).

export const HAND_BUILT_PLAYLIST_EVENT_TYPES = Object.freeze(['hand-built-playlist-changed', 'hand-built-playlist-track-chosen',
  'hand-built-playlist-download-started', 'hand-built-playlist-downloaded', 'hand-built-playlist-download-failed']);

// notice: '' or what went wrong. previewed: the last preview (#287), {trackIds asked for, tracks, transitions} as the
// recipe preview's, which may be of an earlier list; null when there is none. A track asked for but not among its
// tracks is no longer playable.
export function handBuiltPlaylistChanged({trackIds, notice, previewed}) {
  return Object.freeze({type: 'hand-built-playlist-changed', trackIds, notice, previewed});
}

export function handBuiltPlaylistTrackChosen(trackId) {
  return Object.freeze({type: 'hand-built-playlist-track-chosen', trackId});
}

export function handBuiltPlaylistDownloadStarted() {
  return Object.freeze({type: 'hand-built-playlist-download-started'});
}

export function handBuiltPlaylistDownloaded() {
  return Object.freeze({type: 'hand-built-playlist-downloaded'});
}

export function handBuiltPlaylistDownloadFailed(message) {
  return Object.freeze({type: 'hand-built-playlist-download-failed', message});
}
