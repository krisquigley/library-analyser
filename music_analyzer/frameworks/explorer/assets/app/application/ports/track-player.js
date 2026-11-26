// The player that plays a track's audio (#258), as the listen-to-track use case needs it.
// load(trackId) plays that track from its start, replacing any other; pause() and resume() act on it; stop() silences
// and empties the player; seek(seconds) moves it to that point (#283). What the player then does comes back to the use
// case as reports, {kind, trackId, message}; a 'progressed' report also carries {position, duration}, duration null
// while it is unknown.

export const TRACK_PLAYER = Object.freeze({name: 'TrackPlayer', operations: Object.freeze(['load', 'pause', 'resume', 'stop', 'seek'])});
