// Which tracks the graph filters keep (#146): a BPM range and any of the chosen genres.

const DEFAULT_GENRE_FILTER_THRESHOLD = 0.1;

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
