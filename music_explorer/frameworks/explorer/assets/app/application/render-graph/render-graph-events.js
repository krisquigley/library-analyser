// What happens to the drawing of the graph (#146). Each event is plain data.

export const GRAPH_RENDERING_EVENT_TYPES = Object.freeze(['graph-rendering-paused', 'graph-rendering-resumed']);

export function graphRenderingEvent(type) {
  return Object.freeze({type});
}
