// What happens while the library view refreshes (#146). Each event carries the refresh's state after it;
// a failure also carries the message the listener reads.

export const LIBRARY_REFRESH_EVENT_TYPES = Object.freeze(['library-refresh-started', 'library-state-loading', 'library-loaded',
  'library-refresh-yielded', 'library-refresh-failed']);

export function libraryRefreshEvent(type, fields) {
  return Object.freeze({type, ...fields});
}
