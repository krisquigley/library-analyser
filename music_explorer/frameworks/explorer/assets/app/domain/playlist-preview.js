// The lifecycle of a playlist preview (#138), as a transitions table. A newer preview may start while one is in flight.

const PLAYLIST_PREVIEW_TRANSITIONS = Object.freeze({
  idle: Object.freeze({start: 'previewing'}),
  previewing: Object.freeze({start: 'previewing', succeed: 'previewed', fail: 'failed'}),
  previewed: Object.freeze({start: 'previewing'}),
  failed: Object.freeze({start: 'previewing'}),
});

export const PLAYLIST_PREVIEW_STATES = Object.freeze(Object.keys(PLAYLIST_PREVIEW_TRANSITIONS));

export class PlaylistPreviewTransitionError extends Error {}

export function nextPlaylistPreviewState(state, action) {
  const next = Object.hasOwn(PLAYLIST_PREVIEW_TRANSITIONS, state) && PLAYLIST_PREVIEW_TRANSITIONS[state][action];
  if (!next) throw new PlaylistPreviewTransitionError(`A playlist preview cannot ${action} while ${state}`);
  return next;
}
