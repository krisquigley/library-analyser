// The Explorer's HTTP API, as the use cases need it (#146). Each use case requires only
// the operations it uses; the gateway provides them all.
// downloadPlaylist(recipe) resolves to {filename, contents, contentType, warning}.
// loadMoodGraph(mood) resolves to the graph response as the server sent it.
// searchTracks({query, cursor}) resolves to a page, {tracks, metadata, nextCursor}.
// Both reject with an Error whose message the listener can read.

export const PLAYLIST_DOWNLOADS = Object.freeze({name: 'ExplorerApi', operations: Object.freeze(['downloadPlaylist'])});
export const MOOD_GRAPHS = Object.freeze({name: 'ExplorerApi', operations: Object.freeze(['loadMoodGraph'])});
export const TRACK_SEARCHES = Object.freeze({name: 'ExplorerApi', operations: Object.freeze(['searchTracks'])});
export const EXPLORER_API = Object.freeze({name: 'ExplorerApi',
  operations: Object.freeze([...PLAYLIST_DOWNLOADS.operations, ...MOOD_GRAPHS.operations, ...TRACK_SEARCHES.operations])});
