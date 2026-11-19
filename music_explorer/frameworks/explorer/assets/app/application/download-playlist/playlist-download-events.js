// What happens while a listener drafts and downloads a playlist (#146).

export const PLAYLIST_DOWNLOAD_EVENT_TYPES = Object.freeze([
  'playlist-draft-edited', 'playlist-download-started', 'playlist-downloaded', 'playlist-download-failed']);

export function playlistDraftEdited(draft) {
  return Object.freeze({type: 'playlist-draft-edited', draft});
}

export function playlistDownloadStarted() {
  return Object.freeze({type: 'playlist-download-started'});
}

export function playlistDownloaded({filename, warning}) {
  return Object.freeze({type: 'playlist-downloaded', filename, warning});
}

export function playlistDownloadFailed(message) {
  return Object.freeze({type: 'playlist-download-failed', message});
}
