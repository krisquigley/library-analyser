// The camera's focus on the current track (#146). An accepted selection asks for one focus; the graph takes
// it once it can show the track, and the arc runs frame by frame. The listener's own camera input claims the
// view, which ends any request and arc. A chosen track claims the view too, and its acceptance asks for focus
// only while that claim still owns the view. The scene's Three.js work and frame scheduling stay outside.

import {cameraFocusCancelCause, cameraFocusState, nextCameraFocusState} from '../../domain/camera-focus.js';
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

  function cancel(cause) {
    cameraFocusCancelCause(cause);
    const {frame, focusGeneration} = read();
    transition('cancel', {frame: null, focusGeneration: focusGeneration + 1});
    if (frame != null) eventBus.publish(cameraFocusEvent('camera-focus-cancelled', {frame, cause}));
  }

  function claimView(cause) {
    cancel(cause);
    const viewIntent = read().viewIntent + 1;
    transition('claim-view', {viewIntent, pendingTrackId: null});
    eventBus.publish(cameraFocusEvent('camera-view-claimed', {viewIntent}));
    return viewIntent;
  }

  function claimViewForSelection(cause) {
    focusSession.write({selectionViewIntent: claimView(cause)});
  }

  function requestForAcceptedSelection(trackId) {
    const {viewIntent, selectionViewIntent} = read();
    if (selectionViewIntent !== viewIntent) return false;
    request(trackId);
    return true;
  }

  function request(trackId) {
    cancel('new-selection');
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
    cancel('new-focus');
    const {focusGeneration} = read();
    eventBus.publish(cameraFocusEvent('camera-focus-started', {focusGeneration}));
    return focusGeneration;
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
    cancel, claimView, claimViewForSelection, request, requestForAcceptedSelection, take, begin, frameScheduled, frameRan, finished,
    peek: () => read().pendingTrackId,
    viewIntent: () => read().viewIntent,
  });
}
