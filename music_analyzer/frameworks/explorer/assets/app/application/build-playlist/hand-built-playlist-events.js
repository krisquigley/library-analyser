// What happens while the listener builds a playlist by hand from the graph's labels (#278).

export const HAND_BUILT_PLAYLIST_EVENT_TYPES = Object.freeze(['hand-built-playlist-changed', 'hand-built-playlist-track-chosen',
  'hand-built-playlist-download-started', 'hand-built-playlist-downloaded', 'hand-built-playlist-download-failed']);

// labels: [{trackId, title, artist}] for the tracks labelled so far, in playlist order; notice: '' or what went wrong.
export function handBuiltPlaylistChanged({trackIds, labels, notice}) {
  return Object.freeze({type: 'hand-built-playlist-changed', trackIds, labels, notice});
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
