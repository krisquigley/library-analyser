// The current track (#146): a transitions table from the listener's choice, or an undo or reset,
// through the server's answer to the track's detail on screen. A newer choice always replaces one in flight.

const REDIRECTABLE = Object.freeze({choose: 'choosing', rewind: 'rewinding'});
const SETTLED = Object.freeze({...REDIRECTABLE, 'load-detail': 'loading-detail', clear: 'none'});
const AWAITING_SERVER = Object.freeze({...REDIRECTABLE, 'accept-track': 'loading-detail', 'accept-none': 'none', refuse: 'refused'});

const TRACK_SELECTION_TRANSITIONS = Object.freeze({
  none: SETTLED,
  choosing: AWAITING_SERVER,
  rewinding: AWAITING_SERVER,
  'loading-detail': Object.freeze({...SETTLED, 'show-detail': 'shown', 'fail-detail': 'detail-failed'}),
  shown: SETTLED,
  'detail-failed': SETTLED,
  refused: SETTLED,
});

export function awaitingServer(state) {
  return state === 'choosing' || state === 'rewinding';
}

export const TRACK_SELECTION_STATES = Object.freeze(Object.keys(TRACK_SELECTION_TRANSITIONS));

export class TrackSelectionTransitionError extends Error {}

export function nextTrackSelectionState(state, action) {
  const next = Object.hasOwn(TRACK_SELECTION_TRANSITIONS, state) && TRACK_SELECTION_TRANSITIONS[state][action];
  if (!next) throw new TrackSelectionTransitionError(`A track selection cannot ${action} while ${state}`);
  return next;
}
