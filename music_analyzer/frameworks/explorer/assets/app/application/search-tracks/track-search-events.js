// What happens while the listener searches the library's tracks (#146).
// Each event carries the search as it then stands: {searchState, results, failure}.

export const TRACK_SEARCH_EVENT_TYPES = Object.freeze(['track-search-edited', 'track-search-started', 'track-page-loaded',
  'track-search-failed']);

export function trackSearchEvent(type, {searchState, results, failure}) {
  return Object.freeze({type, searchState, results, failure});
}
