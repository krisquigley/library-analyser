// Listening to a track from the playlist preview (#258). The listener's commands ask the player; what the player
// reports moves the playback on and is published. A report about a track no longer asked for, or one the playback
// cannot take (a late "playing" after a stop), is ignored.

import {nextTrackPlayerState, trackPlayerAllows} from '../../domain/track-player.js';
import {EVENT_BUS} from '../ports/event-bus.js';
import {requirePort} from '../ports/port.js';
import {TRACK_PLAYER} from '../ports/track-player.js';
import {trackPlaybackFailed, trackPlaybackLoading, trackPlaybackPaused, trackPlaybackPlaying, trackPlaybackStopped}
  from './track-playback-events.js';

const REPORTS = Object.freeze({
  playing: Object.freeze({action: 'play', event: trackPlaybackPlaying}),
  paused: Object.freeze({action: 'pause', event: trackPlaybackPaused}),
  ended: Object.freeze({action: 'end', event: trackPlaybackStopped}),
  failed: Object.freeze({action: 'fail', event: trackPlaybackFailed}),
});

export function createTrackPlayback({trackPlayer, eventBus}) {
  requirePort(TRACK_PLAYER, trackPlayer);
  requirePort(EVENT_BUS, eventBus);
  let state = 'stopped';
  let trackId = null;

  function move(action, event) {
    state = nextTrackPlayerState(state, action);
    eventBus.publish(event);
  }

  // The button beside a track: plays it, or pauses and plays on the one already asked for.
  function toggle(requested) {
    if (requested === trackId && (state === 'playing' || state === 'loading')) return trackPlayer.pause();
    if (requested === trackId && state === 'paused') return trackPlayer.resume();
    trackId = requested;
    move('load', trackPlaybackLoading(trackId));
    trackPlayer.load(trackId);
  }

  function stop() {
    if (state === 'stopped') return;
    trackPlayer.stop();
    move('stop', trackPlaybackStopped(trackId));
  }

  function heard(report) {
    const reported = REPORTS[report.kind];
    if (!reported || report.trackId !== trackId || !trackPlayerAllows(state, reported.action)) return;
    move(reported.action, reported.event(trackId, report.message));
  }

  return Object.freeze({toggle, stop, heard, state: () => state});
}
