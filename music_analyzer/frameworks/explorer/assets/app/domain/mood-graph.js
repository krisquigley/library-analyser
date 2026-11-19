// The mood-axis graph model (#146): tracks placed on their valence, arousal and mood axes.
// Colour is relative to this library only; the musical coordinates stay native and are never clipped.

import {displayNumber} from './display-number.js';

const MOOD_GRAPH_SCALE = 180;
const GENRE_OPTION_MINIMUM = 0.1;
const DEFAULT_GENRE_THRESHOLD = 0.1;

export function moodNodeColor(valence, arousal) {
  const hue = 215 - 195 * valence, saturation = 48 + 32 * arousal, lightness = 27 + 33 * arousal;
  return `hsl(${hue} ${saturation}% ${lightness}%)`;
}

export function moodToTrack(requested, model) {
  return requested && model.availableMoods.includes(requested) ? requested : (model.selectedMood || '');
}

export function moodGraphModel(graph, {genreThresholdApplies = false} = {}) {
  const positioned = graph.positioned || [];
  const colorRanges = {valence: axisRange(positioned, 'x'), arousal: axisRange(positioned, 'y')};
  const nodes = positioned.map(track => moodGraphNode(track, colorRanges, genreThresholdApplies));
  const ids = new Set(nodes.map(node => node.id));
  const links = (graph.edges || []).filter(edge => ids.has(edge.a) && ids.has(edge.b)).map(moodGraphLink);
  return {nodes, links, colorRanges, unpositioned: graph.unpositioned || [], availableMoods: graph.available_moods || [],
    selectedMood: graph.selected_mood || '', metadata: graph.metadata || {}, genreOptions: genreOptionsOf(nodes)};
}

function moodGraphNode(track, colorRanges, genreThresholdApplies) {
  const at = axisValue => axisValue.normalized * MOOD_GRAPH_SCALE * 2;
  const label = track.display_label || track.track_id;
  return {
    color: moodNodeColor(relativeAxis(track.x.raw, colorRanges.valence), relativeAxis(track.y.raw, colorRanges.arousal)),
    id: track.track_id, label, name: label,
    fx: at(track.x), fy: at(track.y), fz: at(track.z), x: at(track.x), y: at(track.y), z: at(track.z),
    axis: {x: track.x, y: track.y, z: track.z},
    moodScore: track.mood_score || null, bpm: track.bpm, genres: track.genres || [],
    genreThreshold: track.genre_threshold == null ? DEFAULT_GENRE_THRESHOLD : track.genre_threshold,
    genreThresholdApplies, reasons: track.reasons || [],
  };
}

function moodGraphLink(edge) {
  return {source: edge.a, target: edge.b, name: `relatedness ${displayNumber(edge.score)}: ${edge.explanation || ''}`,
    score: edge.score, explanation: edge.explanation, provenance: edge.provenance,
    supportedGroupCount: edge.supported_group_count};
}

function genreOptionsOf(nodes) {
  const labels = nodes.flatMap(node => (node.genres || [])
    .filter(([, score]) => Number.isFinite(score) && score > GENRE_OPTION_MINIMUM).map(([label]) => label));
  return [...new Set(labels)].sort();
}

function axisRange(positioned, axis) {
  let min = Infinity, max = -Infinity;
  for (const track of positioned) {
    const value = track[axis].raw;
    if (Number.isFinite(value)) { min = Math.min(min, value); max = Math.max(max, value); }
  }
  return min === Infinity ? null : [min, max];
}

function relativeAxis(value, range) {
  return range && range[0] !== range[1] ? (value - range[0]) / (range[1] - range[0]) : 0.5;
}
