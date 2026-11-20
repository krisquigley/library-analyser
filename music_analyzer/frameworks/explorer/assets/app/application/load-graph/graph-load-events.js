// What happens while the library graph loads and is filtered (#146).

export const GRAPH_LOAD_EVENT_TYPES = Object.freeze(['graph-controls-edited', 'graph-load-started', 'graph-model-building', 'graph-model-built',
  'graph-render-due', 'graph-ready', 'graph-load-failed', 'graph-filters-applied']);

export function graphControlsEdited(controls) {
  return Object.freeze({type: 'graph-controls-edited', controls});
}

export function graphLoadStarted() {
  return Object.freeze({type: 'graph-load-started'});
}

export function graphModelBuilding() {
  return Object.freeze({type: 'graph-model-building'});
}

export function graphModelBuilt({model, visible, controls}) {
  return Object.freeze({type: 'graph-model-built', model, visible, controls});
}

export function graphRenderDue(visible) {
  return Object.freeze({type: 'graph-render-due', visible});
}

export function graphReady({model, visible}) {
  return Object.freeze({type: 'graph-ready', model, visible});
}

export function graphLoadFailed(message) {
  return Object.freeze({type: 'graph-load-failed', message});
}

export function graphFiltersApplied({shown, model, visible}) {
  return Object.freeze({type: 'graph-filters-applied', shown, model, visible});
}
