// The HandBuiltPlaylistStore port over the browser's local storage (#278): the track IDs as JSON under one key.
// Whatever was kept is handed back as it is, as text when it is not JSON; the use case reads it against the playlist's rules.

export const HAND_BUILT_PLAYLIST_KEY = 'music-explorer.hand-built-playlist.v1';

export function browserHandBuiltPlaylistStore(storage) {
  function available() {
    if (!storage) throw new Error('This browser offers no local storage');
    return storage;
  }

  return Object.freeze({
    load() {
      const kept = available().getItem(HAND_BUILT_PLAYLIST_KEY);
      return kept === null ? null : keptPlaylistOrText(kept);
    },
    save(trackIds) {
      available().setItem(HAND_BUILT_PLAYLIST_KEY, JSON.stringify(trackIds));
    },
  });
}

function keptPlaylistOrText(kept) {
  try {
    return JSON.parse(kept);
  } catch {
    return kept;
  }
}
