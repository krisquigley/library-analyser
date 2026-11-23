// What happens while a listener previews the drafted playlist (#138).

export const PLAYLIST_PREVIEW_EVENT_TYPES = Object.freeze([
  'playlist-preview-started', 'playlist-previewed', 'playlist-preview-failed']);

export function playlistPreviewStarted() {
  return Object.freeze({type: 'playlist-preview-started'});
}

export function playlistPreviewed(preview) {
  return Object.freeze({type: 'playlist-previewed', preview});
}

export function playlistPreviewFailed(message) {
  return Object.freeze({type: 'playlist-preview-failed', message});
}
