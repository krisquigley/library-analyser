// Hands a downloaded playlist to the listener as a file (#146).
// save({filename, contents, contentType}) throws if the file could not be offered.

export const PLAYLIST_FILE = Object.freeze({name: 'PlaylistFile', operations: Object.freeze(['save'])});
