// What happens to the camera's focus (#146). Each event is plain data.
// camera-focus-cancelled carries the frame that was in flight, for the scene to cancel.

export const CAMERA_FOCUS_EVENT_TYPES = Object.freeze(['camera-view-claimed', 'camera-focus-cancelled', 'camera-focus-requested',
  'camera-focus-started', 'camera-focus-finished']);

export function cameraFocusEvent(type, fields = {}) {
  return Object.freeze({type, ...fields});
}
