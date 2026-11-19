// Where the camera's focus is kept between commands (#146).
// read() returns {pendingTrackId, frame, viewIntent, focusGeneration}: the track waiting to be focused,
// the animation frame in flight, and the generations of the listener's view intent and of the arc.
// write(changes) replaces the fields it is given.

export const CAMERA_FOCUS_SESSION = Object.freeze({name: 'CameraFocusSession', operations: Object.freeze(['read', 'write'])});
