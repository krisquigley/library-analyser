// Listening to a track from the playlist preview (#258): one track at a time, its lifecycle as a transitions table.
// Another track may be loaded at any time; a failed one waits for a new load or a stop.

const TRACK_PLAYER_TRANSITIONS = Object.freeze({
  stopped: Object.freeze({load: 'loading'}),
  loading: Object.freeze({load: 'loading', play: 'playing', pause: 'paused', fail: 'failed', stop: 'stopped'}),
  playing: Object.freeze({load: 'loading', play: 'playing', pause: 'paused', end: 'stopped', fail: 'failed', stop: 'stopped'}),
  paused: Object.freeze({load: 'loading', play: 'playing', pause: 'paused', end: 'stopped', fail: 'failed', stop: 'stopped'}),
  failed: Object.freeze({load: 'loading', stop: 'stopped'}),
});

export const TRACK_PLAYER_STATES = Object.freeze(Object.keys(TRACK_PLAYER_TRANSITIONS));

export class TrackPlayerTransitionError extends Error {}

export function trackPlayerAllows(state, action) {
  return Object.hasOwn(TRACK_PLAYER_TRANSITIONS, state) && Object.hasOwn(TRACK_PLAYER_TRANSITIONS[state], action);
}

export function nextTrackPlayerState(state, action) {
  if (!trackPlayerAllows(state, action)) throw new TrackPlayerTransitionError(`A track cannot ${action} while ${state}`);
  return TRACK_PLAYER_TRANSITIONS[state][action];
}

// #283: the listener may move a playing or paused track to another point, kept within the track's length when it is known.
const SEEKABLE_STATES = Object.freeze(['playing', 'paused']);

export function trackPlayerSeeks(state) {
  return SEEKABLE_STATES.includes(state);
}

export function seekPosition(requested, duration) {
  if (typeof requested !== 'number' || !Number.isFinite(requested)) return null;
  const longest = Number.isFinite(duration) ? duration : Infinity;
  return Math.min(Math.max(requested, 0), longest);
}
