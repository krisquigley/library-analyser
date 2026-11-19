// The camera's focus (#146): a request waits until the graph can show it, then animates along its arc.
// The listener's own camera input claims the view and ends both. The state is derived, never stored.

const ANYWHERE = Object.freeze({request: 'pending', 'claim-view': 'idle'});

const CAMERA_FOCUS_TRANSITIONS = Object.freeze({
  // A picked node is framed at once, without waiting: it animates straight from idle.
  idle: Object.freeze({...ANYWHERE, cancel: 'idle', animate: 'animating'}),
  pending: Object.freeze({...ANYWHERE, cancel: 'pending', animate: 'animating', skip: 'idle'}),
  animating: Object.freeze({...ANYWHERE, cancel: 'idle', animate: 'animating', 'next-frame': 'animating', finish: 'idle'}),
});

export const CAMERA_FOCUS_STATES = Object.freeze(Object.keys(CAMERA_FOCUS_TRANSITIONS));

export class CameraFocusTransitionError extends Error {}

export function cameraFocusState({pendingTrackId, frame}) {
  if (frame != null) return 'animating';
  return pendingTrackId != null ? 'pending' : 'idle';
}

export function nextCameraFocusState(state, action) {
  const next = Object.hasOwn(CAMERA_FOCUS_TRANSITIONS, state) && CAMERA_FOCUS_TRANSITIONS[state][action];
  if (!next) throw new CameraFocusTransitionError(`A camera focus cannot ${action} while ${state}`);
  return next;
}
