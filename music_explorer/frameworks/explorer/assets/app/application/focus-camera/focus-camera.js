// The camera's focus on the current track (#146). An accepted selection asks for one focus; the graph takes
// it once it can show the track, and the arc runs frame by frame. The listener's own camera input claims the
// view, which ends any request and arc. The scene's Three.js work and frame scheduling stay outside.

import {cameraFocusState, nextCameraFocusState} from '../../domain/camera-focus.js';
import {EVENT_BUS} from '../ports/event-bus.js';
import {CAMERA_FOCUS_SESSION} from '../ports/camera-focus-session.js';
import {requirePort} from '../ports/port.js';
import {cameraFocusEvent} from './camera-focus-events.js';

export function createCameraFocus({focusSession, eventBus}) {
  requirePort(CAMERA_FOCUS_SESSION, focusSession);
  requirePort(EVENT_BUS, eventBus);
  const read = () => focusSession.read();

  function transition(action, changes = {}) {
    nextCameraFocusState(cameraFocusState(read()), action);
    focusSession.write(changes);
  }

  function cancel() {
    const {frame, focusGeneration} = read();
    transition('cancel', {frame: null, focusGeneration: focusGeneration + 1});
    if (frame != null) eventBus.publish(cameraFocusEvent('camera-focus-cancelled', {frame}));
  }

  function claimView() {
    cancel();
    const viewIntent = read().viewIntent + 1;
    transition('claim-view', {viewIntent, pendingTrackId: null});
    eventBus.publish(cameraFocusEvent('camera-view-claimed', {viewIntent}));
    return viewIntent;
  }

  function request(trackId) {
    cancel();
    transition('request', {pendingTrackId: trackId ?? null});
    if (trackId != null) eventBus.publish(cameraFocusEvent('camera-focus-requested', {trackId}));
  }

  function take(currentTrackId) {
    const {pendingTrackId} = read();
    if (pendingTrackId == null) return null;
    transition('skip', {pendingTrackId: null});
    return pendingTrackId === currentTrackId ? pendingTrackId : null;
  }

  function begin() {
    cancel();
    return read().focusGeneration;
  }

  function frameScheduled(arc, frame) {
    if (arc !== read().focusGeneration) return;
    transition('animate', {frame});
  }

  function frameRan(arc) {
    if (arc !== read().focusGeneration) return false;
    if (read().frame != null) transition('next-frame', {frame: null});
    return true;
  }

  function finished(arc) {
    if (arc !== read().focusGeneration) return;
    eventBus.publish(cameraFocusEvent('camera-focus-finished'));
  }

  return Object.freeze({
    cancel, claimView, request, take, begin, frameScheduled, frameRan, finished,
    peek: () => read().pendingTrackId,
    viewIntent: () => read().viewIntent,
  });
}
