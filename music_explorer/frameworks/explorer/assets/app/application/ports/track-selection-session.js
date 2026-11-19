// Where the current track is kept between commands (#146).
// read() returns {snapshot, epoch, selectionState}: the library state as last known (its current_track_id
// is the current track), the server's selection epoch, and the selection's lifecycle state.
// write(changes) replaces the fields it is given.

export const TRACK_SELECTION_SESSION = Object.freeze({name: 'TrackSelectionSession', operations: Object.freeze(['read', 'write'])});
