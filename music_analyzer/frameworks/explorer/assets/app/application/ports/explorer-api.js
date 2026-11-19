// The Explorer's HTTP API, as the use cases need it (#146).
// downloadPlaylist(recipe) resolves to {filename, contents, contentType, warning}
// and rejects with an Error whose message the listener can read.

export const EXPLORER_API = Object.freeze({name: 'ExplorerApi', operations: Object.freeze(['downloadPlaylist'])});
