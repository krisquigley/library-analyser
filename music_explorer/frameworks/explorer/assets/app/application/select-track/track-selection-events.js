// What happens to the current track (#146). Each event is plain data.

export const TRACK_SELECTION_EVENT_TYPES = Object.freeze(['track-chosen', 'selection-rewinding', 'selection-accepted',
  'selection-refused', 'library-selection-changed', 'no-track-selected', 'track-detail-loading', 'track-detail-loaded',
  'track-detail-failed']);

export function trackSelectionEvent(type, fields = {}) {
  return Object.freeze({type, ...fields});
}

export function failureOf(error) {
  return Object.freeze({message: error && error.message ? error.message : String(error)});
}
