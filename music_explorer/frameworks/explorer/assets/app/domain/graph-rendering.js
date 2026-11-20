// Drawing the graph on demand (#86, #146). The vendor loop redraws WebGL every frame even when nothing moves,
// which starves the page's main thread under software rendering. The graph is drawn while its view can change
// and pauses once it has been quiet for a while; anything that can change the view wakes it.

export const GRAPH_RENDER_IDLE_MS = 500;

const GRAPH_RENDERING_TRANSITIONS = Object.freeze({
  drawing: Object.freeze({wake: 'drawing', pause: 'paused'}),
  paused: Object.freeze({wake: 'drawing'}),
});

export const GRAPH_RENDERING_STATES = Object.freeze(Object.keys(GRAPH_RENDERING_TRANSITIONS));

export class GraphRenderingTransitionError extends Error {}

export function nextGraphRenderingState(state, action) {
  const next = Object.hasOwn(GRAPH_RENDERING_TRANSITIONS, state) && GRAPH_RENDERING_TRANSITIONS[state][action];
  if (!next) throw new GraphRenderingTransitionError(`The graph rendering cannot ${action} while ${state}`);
  return next;
}

export function quietLongEnough(quietSince, now) {
  return quietSince !== null && now - quietSince >= GRAPH_RENDER_IDLE_MS;
}
