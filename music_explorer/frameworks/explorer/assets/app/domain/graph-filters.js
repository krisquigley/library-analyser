// The graph controls (#146): the tracked mood, and the filters on which tracks the graph shows,
// a BPM range and any of the chosen genres.

const DEFAULT_GENRE_FILTER_THRESHOLD = 0.1;

export const EMPTY_GRAPH_CONTROLS = Object.freeze({mood: '', bpmMin: null, bpmMax: null, genres: Object.freeze([])});

export function editGraphControls(controls, changes) {
  const unknown = Object.keys(changes).find(control => !Object.hasOwn(EMPTY_GRAPH_CONTROLS, control));
  if (unknown) throw new Error(`Unknown graph control: ${unknown}`);
  const edited = {...controls, ...changes};
  return Object.freeze({...edited, genres: Object.freeze([...edited.genres])});
}

export function clearedGraphFilters(controls) {
  return editGraphControls(controls, {bpmMin: null, bpmMax: null, genres: []});
}

export function passesGraphFilters(node, filters) {
  if (filters.bpmMin != null && (node.bpm == null || node.bpm < filters.bpmMin)) return false;
  if (filters.bpmMax != null && (node.bpm == null || node.bpm > filters.bpmMax)) return false;
  const genres = filters.genres || [];
  return !genres.length || scoresAnyGenre(node, genres);
}

export function applyMoodGraphFilters(model, filters) {
  const nodes = model.nodes.filter(node => passesGraphFilters(node, filters || {}));
  const ids = new Set(nodes.map(node => node.id));
  const endpoint = end => String((end && end.id) || end);
  return {nodes, links: model.links.filter(link => ids.has(endpoint(link.source)) && ids.has(endpoint(link.target))),
    unpositioned: model.unpositioned};
}

function scoresAnyGenre(node, genres) {
  const scores = Object.fromEntries(node.genres);
  const threshold = node.genreThresholdApplies && Number.isFinite(node.genreThreshold)
    ? node.genreThreshold : DEFAULT_GENRE_FILTER_THRESHOLD;
  return genres.some(genre => Number.isFinite(scores[genre]) && scores[genre] > threshold);
}
