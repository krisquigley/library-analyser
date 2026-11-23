// Where the camera's focus is kept between commands (#146).
// read() returns {pendingTrackId, frame, viewIntent, selectionViewIntent, focusGeneration}: the track waiting to be
// focused, the animation frame in flight, the generation of the view intent, the one the latest chosen track
// claimed, and the generation of the arc.
// write(changes) replaces the fields it is given.

export const CAMERA_FOCUS_SESSION = Object.freeze({name: 'CameraFocusSession', operations: Object.freeze(['read', 'write'])});
