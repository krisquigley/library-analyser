// What the graph status panel and the graph controls show (#146).
// The graph's stored-snapshot status is described in fixed words; the API's reason and action are never shown.

const GRAPH_BUILD_ADVICE = 'Run music-analyzer graph build --database DB, then reload this read-only explorer.';

export const GRAPH_IDLE_STATUS = Object.freeze({status: 'idle',
  message: 'The library graph starts automatically; search and track detail remain usable.'});

const GRAPH_SNAPSHOT_MESSAGES = Object.freeze({
  ready: count => `Graph ready: ${count} positioned tracks`,
  stale: count => `Graph stale: showing the last stored snapshot for ${count} positioned tracks. ${GRAPH_BUILD_ADVICE}`,
  build_needed: () => `Graph needs a build: no current stored graph snapshot is available. ${GRAPH_BUILD_ADVICE}`,
  failed: () => `Graph failed: the last stored graph build did not complete successfully. ${GRAPH_BUILD_ADVICE}`,
  building: () => `Graph building: a stored graph snapshot is not ready yet. ${GRAPH_BUILD_ADVICE}`,
});

const GRAPH_EVENT_STATUSES = Object.freeze({
  'graph-load-started': () => ({status: 'loading',
    message: 'Loading graph. The track list, search, history, and detail remain usable.'}),
  'graph-model-built': event => ({status: 'rendering', message: `Rendering ${event.visible.nodes.length} positioned tracks`}),
  'graph-ready': event => readyStatus(event),
  'graph-load-failed': event => ({status: 'error', message: `Graph failed: ${event.message}`}),
  'graph-filters-applied': event => (event.shown ? readyStatus(event) : null),
});

export function graphStatusMessage(graphStatus, positionedCount) {
  const state = graphStatus && typeof graphStatus.state === 'string' ? graphStatus.state : 'ready';
  const message = Object.hasOwn(GRAPH_SNAPSHOT_MESSAGES, state) ? GRAPH_SNAPSHOT_MESSAGES[state]
    : count => `Graph status unavailable: showing ${count} positioned tracks from the stored snapshot. ${GRAPH_BUILD_ADVICE}`;
  return message(positionedCount);
}

export function presentGraphLoadEvent(event) {
  return Object.hasOwn(GRAPH_EVENT_STATUSES, event.type) ? GRAPH_EVENT_STATUSES[event.type](event) : null;
}

export function graphControlOptionsViewModel(model, controls) {
  const moods = model.availableMoods.length ? model.availableMoods : [''];
  return {
    moodChoices: moods.map(mood => ({value: mood, label: mood || 'No supported moods', selected: mood === controls.mood})),
    genreChoices: model.genreOptions.map(genre => ({value: genre, label: genre, selected: controls.genres.includes(genre)})),
  };
}

export function graphControlValuesViewModel(controls) {
  const bpmText = bound => (bound == null ? '' : String(bound));
  return {bpmMin: bpmText(controls.bpmMin), bpmMax: bpmText(controls.bpmMax), genres: [...controls.genres]};
}

function readyStatus({model, visible}) {
  return {status: 'ready', message: graphStatusMessage(model.metadata.graph_status, visible.nodes.length)};
}
