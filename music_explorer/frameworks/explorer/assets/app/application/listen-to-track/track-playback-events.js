// What happens while the listener plays a track from the playlist preview (#258).

export const TRACK_PLAYBACK_STATE_EVENT_TYPES = Object.freeze(['track-playback-loading', 'track-playback-playing',
  'track-playback-paused', 'track-playback-stopped', 'track-playback-failed']);
// #283: progress through the track moves no state; it is published as the player reports it.
export const TRACK_PLAYBACK_EVENT_TYPES = Object.freeze([...TRACK_PLAYBACK_STATE_EVENT_TYPES, 'track-playback-progressed']);

export function trackPlaybackLoading(trackId) {
  return Object.freeze({type: 'track-playback-loading', trackId});
}

export function trackPlaybackPlaying(trackId) {
  return Object.freeze({type: 'track-playback-playing', trackId});
}

export function trackPlaybackPaused(trackId) {
  return Object.freeze({type: 'track-playback-paused', trackId});
}

export function trackPlaybackStopped(trackId) {
  return Object.freeze({type: 'track-playback-stopped', trackId});
}

export function trackPlaybackFailed(trackId, message) {
  return Object.freeze({type: 'track-playback-failed', trackId, message});
}

export function trackPlaybackProgressed(trackId, {position, duration}) {
  return Object.freeze({type: 'track-playback-progressed', trackId, position, duration});
}
