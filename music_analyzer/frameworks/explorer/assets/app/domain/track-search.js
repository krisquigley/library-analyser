// Searching the library's tracks (#146): a transitions table over the search, and its pages of results.

const TRACK_SEARCH_FETCHABLE = Object.freeze({type: 'debouncing', clear: 'idle', fetch: 'loading'});

const TRACK_SEARCH_TRANSITIONS = Object.freeze({
  idle: TRACK_SEARCH_FETCHABLE,
  debouncing: TRACK_SEARCH_FETCHABLE,
  loading: Object.freeze({type: 'debouncing', clear: 'idle', succeed: 'ready', fail: 'failed'}),
  ready: TRACK_SEARCH_FETCHABLE,
  failed: TRACK_SEARCH_FETCHABLE,
});

export const TRACK_SEARCH_STATES = Object.freeze(Object.keys(TRACK_SEARCH_TRANSITIONS));

export class TrackSearchTransitionError extends Error {}

export function nextTrackSearchState(state, action) {
  const next = Object.hasOwn(TRACK_SEARCH_TRANSITIONS, state) && TRACK_SEARCH_TRANSITIONS[state][action];
  if (!next) throw new TrackSearchTransitionError(`A track search cannot ${action} while ${state}`);
  return next;
}

export function emptyTrackResults(query = '') {
  return Object.freeze({query, tracks: Object.freeze([]), metadata: Object.freeze({}), nextCursor: null});
}

export function trackResultsWithPage(results, page, {append = false} = {}) {
  const tracks = append ? [...results.tracks, ...page.tracks] : [...page.tracks];
  return Object.freeze({query: results.query, tracks: Object.freeze(tracks), metadata: page.metadata, nextCursor: page.nextCursor});
}
