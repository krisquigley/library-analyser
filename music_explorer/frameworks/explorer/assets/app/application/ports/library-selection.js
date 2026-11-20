// The listener's selection, as a library refresh needs it (#146).
// generation() names the latest selection command; awaitingServer() is true while one waits for the server;
// reconcile(snapshot) adopts the library state the server holds; loadDetail(generation) loads the current track's detail.

export const LIBRARY_SELECTION = Object.freeze({name: 'LibrarySelection',
  operations: Object.freeze(['generation', 'awaitingServer', 'reconcile', 'loadDetail'])});
