// The lifecycle of loading the library graph (#146), as a transitions table.
// A newer load may start at any point; the older one is then superseded.

const GRAPH_LOAD_TRANSITIONS = Object.freeze({
  idle: Object.freeze({start: 'loading'}),
  loading: Object.freeze({start: 'loading', build: 'rendering', fail: 'failed'}),
  rendering: Object.freeze({start: 'loading', render: 'ready', fail: 'failed'}),
  ready: Object.freeze({start: 'loading'}),
  failed: Object.freeze({start: 'loading'}),
});

export const GRAPH_LOAD_STATES = Object.freeze(Object.keys(GRAPH_LOAD_TRANSITIONS));

export class GraphLoadTransitionError extends Error {}

export function nextGraphLoadState(state, action) {
  const next = Object.hasOwn(GRAPH_LOAD_TRANSITIONS, state) && GRAPH_LOAD_TRANSITIONS[state][action];
  if (!next) throw new GraphLoadTransitionError(`A graph load cannot ${action} while ${state}`);
  return next;
}
