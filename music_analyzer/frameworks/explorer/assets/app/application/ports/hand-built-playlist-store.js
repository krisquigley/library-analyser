// Keeps the hand-built playlist in this browser across reloads (#278).
// load() returns what was last saved, as it was saved (text when it is not JSON), or null when nothing was; it throws
// if the browser refuses.
// save(trackIds) keeps the list; it throws if the browser cannot keep it.

export const HAND_BUILT_PLAYLIST_STORE = Object.freeze({name: 'HandBuiltPlaylistStore', operations: Object.freeze(['load', 'save'])});
