// What the playlist preview's play buttons and its player show for each playback event (#258). The track playing,
// loading or paused has the active button; every other track offers Play. Its progress drives a seek slider (#283).

import {displayDuration} from '../../domain/display-duration.js';

const PLAY_BUTTON = Object.freeze({text: '▶', verb: 'Play', pressed: false});
const PAUSE_BUTTON = Object.freeze({text: '❚❚', verb: 'Pause', pressed: true});
const LOADING_BUTTON = Object.freeze({text: '…', verb: 'Pause', pressed: true});

const PLAYBACK_EVENT_VIEWS = Object.freeze({
  'track-playback-loading': event => playbackView(event.trackId, LOADING_BUTTON, 'Loading the track…'),
  'track-playback-playing': event => playbackView(event.trackId, PAUSE_BUTTON, 'Playing'),
  'track-playback-paused': event => playbackView(event.trackId, PLAY_BUTTON, 'Paused'),
  'track-playback-stopped': () => trackPlaybackViewModel(),
  'track-playback-failed': event => ({activeTrackId: event.trackId, activeButton: {...PLAY_BUTTON}, idleButton: {...PLAY_BUTTON},
    status: {text: `Could not play the track: ${event.message}`, urgent: true}, playerShown: false}),
});

export function trackPlaybackViewModel() {
  return {activeTrackId: null, activeButton: {...PLAY_BUTTON}, idleButton: {...PLAY_BUTTON}, status: {text: '', urgent: false},
    playerShown: false};
}

export function presentTrackPlaybackEvent(event) {
  return PLAYBACK_EVENT_VIEWS[event.type](event);
}

function playbackView(activeTrackId, button, status) {
  return {activeTrackId, activeButton: {...button}, idleButton: {...PLAY_BUTTON}, status: {text: status, urgent: false},
    playerShown: true};
}

export function presentTrackPlaybackProgress({trackId, position, duration}) {
  const length = Number.isFinite(duration) && duration > 0 ? duration : 0;
  const at = displayDuration(position) || '0:00';
  return {trackId, position, duration: length, text: length ? `${at} / ${displayDuration(length)}` : at};
}
