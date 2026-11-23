// Where the playlist the listener is drafting is kept between commands (#138), shared by the use cases that read it.
// read() returns {draft}; write(changes) replaces the fields it is given.

export const PLAYLIST_DRAFT_SESSION = Object.freeze({name: 'PlaylistDraftSession', operations: Object.freeze(['read', 'write'])});
