// Listening to a track from the playlist preview (#258). The listener's commands ask the player; what the player
// reports moves the playback on and is published. A report about a track no longer asked for, or one the playback
// cannot take (a late "playing" after a stop), is ignored.

import {nextTrackPlayerState, seekPosition, trackPlayerAllows, trackPlayerSeeks} from '../../domain/track-player.js';
import {EVENT_BUS} from '../ports/event-bus.js';
import {requirePort} from '../ports/port.js';
import {TRACK_PLAYER} from '../ports/track-player.js';
import {trackPlaybackFailed, trackPlaybackLoading, trackPlaybackPaused, trackPlaybackPlaying, trackPlaybackProgressed,
  trackPlaybackStopped}
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
  let duration = null;

  function move(action, event) {
    state = nextTrackPlayerState(state, action);
    eventBus.publish(event);
  }

  // The button beside a track: plays it, or pauses and plays on the one already asked for.
  function toggle(requested) {
    if (requested === trackId && (state === 'playing' || state === 'loading')) return trackPlayer.pause();
    if (requested === trackId && state === 'paused') return trackPlayer.resume();
    trackId = requested;
    duration = null;
    move('load', trackPlaybackLoading(trackId));
    trackPlayer.load(trackId);
  }

  function stop() {
    if (state === 'stopped') return;
    trackPlayer.stop();
    move('stop', trackPlaybackStopped(trackId));
  }

  // #283: the listener moves the track asked for to another point while it plays or is paused.
  function seek(requested, seconds) {
    const position = seekPosition(seconds, duration);
    if (requested !== trackId || !trackPlayerSeeks(state) || position === null) return;
    trackPlayer.seek(position);
  }

  function heard(report) {
    if (report.kind === 'progressed') return progressed(report);
    const reported = REPORTS[report.kind];
    if (!reported || report.trackId !== trackId || !trackPlayerAllows(state, reported.action)) return;
    move(reported.action, reported.event(trackId, report.message));
  }

  function progressed(report) {
    if (report.trackId !== trackId || state === 'stopped' || state === 'failed') return;
    duration = report.duration;
    eventBus.publish(trackPlaybackProgressed(trackId, report));
  }

  return Object.freeze({toggle, stop, seek, heard, state: () => state});
}
