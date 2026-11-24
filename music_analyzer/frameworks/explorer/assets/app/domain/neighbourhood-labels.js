// The labels over a selected track and its nearest neighbours (#243): their lifecycle as a transitions table, and the
// tracks they name: the selected track first, then its neighbours, no more than one request may name.

const NEIGHBOURHOOD_LABEL_TRANSITIONS = Object.freeze({
  unlabelled: Object.freeze({request: 'labelling', clear: 'unlabelled'}),
  labelling: Object.freeze({request: 'labelling', succeed: 'labelled', fail: 'failed', clear: 'unlabelled'}),
  labelled: Object.freeze({request: 'labelling', clear: 'unlabelled'}),
  failed: Object.freeze({request: 'labelling', clear: 'unlabelled'}),
});

export const NEIGHBOURHOOD_LABEL_STATES = Object.freeze(Object.keys(NEIGHBOURHOOD_LABEL_TRANSITIONS));

export const MOST_LABELLED_TRACKS = 100;

export class NeighbourhoodLabelTransitionError extends Error {}

export function nextNeighbourhoodLabelState(state, action) {
  const next = Object.hasOwn(NEIGHBOURHOOD_LABEL_TRANSITIONS, state) && NEIGHBOURHOOD_LABEL_TRANSITIONS[state][action];
  if (!next) throw new NeighbourhoodLabelTransitionError(`Labels cannot ${action} while ${state}`);
  return next;
}

export function labelledTrackIds(focus) {
  if (!focus.active) return [];
  return [focus.selectedTrackId, ...focus.neighbourIds].slice(0, MOST_LABELLED_TRACKS);
}
