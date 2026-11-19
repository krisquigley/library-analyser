// Where the graph being explored is kept between commands (#146).
// read() returns {loadState, model, visible, controls}; write(changes) replaces the fields it is given.

export const GRAPH_SESSION = Object.freeze({name: 'GraphSession', operations: Object.freeze(['read', 'write'])});
