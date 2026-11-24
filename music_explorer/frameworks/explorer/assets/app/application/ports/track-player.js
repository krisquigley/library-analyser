// The player that plays a track's audio (#258), as the listen-to-track use case needs it.
// load(trackId) plays that track from its start, replacing any other; pause() and resume() act on it; stop() silences
// and empties the player. What the player then does comes back to the use case as reports, {kind, trackId, message}.

export const TRACK_PLAYER = Object.freeze({name: 'TrackPlayer', operations: Object.freeze(['load', 'pause', 'resume', 'stop'])});
