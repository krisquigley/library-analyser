// A use case's session, kept in memory within the page (#146): it provides the GraphSession and TrackSearchSession
// ports. read() returns the session as it stands, frozen; write(changes) replaces the fields it is given.

export function createInMemorySession(initial) {
  let current = Object.freeze({...initial});
  return Object.freeze({
    read: () => current,
    write(changes) { current = Object.freeze({...current, ...changes}); },
  });
}
