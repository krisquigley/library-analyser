// The lifecycle of one playlist download (#146), as a transitions table.

const PLAYLIST_DOWNLOAD_TRANSITIONS = Object.freeze({
  idle: Object.freeze({start: 'downloading'}),
  downloading: Object.freeze({succeed: 'downloaded', fail: 'failed'}),
  downloaded: Object.freeze({start: 'downloading'}),
  failed: Object.freeze({start: 'downloading'}),
});

export const PLAYLIST_DOWNLOAD_STATES = Object.freeze(Object.keys(PLAYLIST_DOWNLOAD_TRANSITIONS));

export class PlaylistDownloadTransitionError extends Error {}

export function nextPlaylistDownloadState(state, action) {
  const next = Object.hasOwn(PLAYLIST_DOWNLOAD_TRANSITIONS, state) && PLAYLIST_DOWNLOAD_TRANSITIONS[state][action];
  if (!next) throw new PlaylistDownloadTransitionError(`A playlist download cannot ${action} while ${state}`);
  return next;
}
