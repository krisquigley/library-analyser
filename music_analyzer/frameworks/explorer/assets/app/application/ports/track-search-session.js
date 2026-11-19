// Where the track search is kept between commands (#146).
// read() returns {searchState, results, failure}; write(changes) replaces the fields it is given.

export const TRACK_SEARCH_SESSION = Object.freeze({name: 'TrackSearchSession', operations: Object.freeze(['read', 'write'])});
