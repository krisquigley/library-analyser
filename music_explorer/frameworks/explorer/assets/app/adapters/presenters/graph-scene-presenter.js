// What the 3D graph shows beside its nodes (#146): the axes, the colour and link legends, and hover labels.

import {displayNumber} from '../../domain/display-number.js';
import {isFocusedLink, isFocusedTrack, neighbourFocus} from '../../domain/neighbour-focus.js';

const SCENE_AXIS_KEYS = Object.freeze(['x', 'y', 'z']);
// The offset leaves the origin outside the occupied node volume; it is not a data minimum.
const AXIS_OFFSET = 18;
const SHORTEST_AXIS = 36;
// Axis coordinates share the fixed display space of the nodes; these are its display units per raw unit.
const SCENE_AXES = Object.freeze([
  Object.freeze({key: 'x', label: 'X valence (native)', color: '#ff7777', units: 360}),
  Object.freeze({key: 'y', label: 'Y arousal (native)', color: '#76dfa0', units: 360}),
  Object.freeze({key: 'z', label: 'Z BPM', color: '#84b9ff', units: 36}),
]);
const RELATEDNESS_LEGEND = 'Link alpha reflects axis-independent relatedness strength from existing stored summaries; higher-score links are more opaque.';

export function graphAxisSpec(nodes) {
  const valid = nodes.filter(node => SCENE_AXIS_KEYS.every(key => Number.isFinite(node[key])));
  if (!valid.length) return [];
  const min = {};
  const max = {};
  for (const key of SCENE_AXIS_KEYS) {
    min[key] = Math.min(...valid.map(node => node[key]));
    max[key] = Math.max(...valid.map(node => node[key]));
  }
  const start = {x: min.x - AXIS_OFFSET, y: min.y - AXIS_OFFSET, z: min.z - AXIS_OFFSET};
  return SCENE_AXES.map(({key, label, color, units}) => {
    const end = {...start, [key]: Math.max(max[key] + AXIS_OFFSET, start[key] + SHORTEST_AXIS)};
    const rawValues = valid.map(node => node.axis && node.axis[key] && node.axis[key].raw).filter(Number.isFinite);
    const references = rawValues.length ? [Math.min(...rawValues), Math.max(...rawValues)] : [min[key] / units, max[key] / units];
    return {key, label, color, start, end, references: references.map(displayNumber)};
  });
}

export function graphColorLegend(model) {
  const ranges = model.colorRanges || {};
  return `Color relative to this library: valence blue → orange/red (${nativeRange(ranges.valence)} native); `
    + `arousal dark/dim → bright (${nativeRange(ranges.arousal)} native). Selected node is larger.`;
}

export function graphRelatednessLegend() {
  return RELATEDNESS_LEGEND;
}

export function relatednessLinkAlpha(link) {
  const score = Number(link && link.score);
  const clamped = Number.isFinite(score) ? Math.max(0, Math.min(1, score)) : 0;
  return Math.round((0.18 + clamped * 0.54) * 100) / 100;
}

export function relatednessLinkColor(link) {
  return `rgba(240,240,240,${relatednessLinkAlpha(link)})`;
}

export function nodeLabel(node) {
  const {x, y, z} = node.axis;
  const mood = node.moodScore ? `${escapeHtml(node.moodScore.label)} ${displayNumber(node.moodScore.raw)} / 1` : 'Selected mood score unavailable';
  return `${escapeHtml(node.label)}<br>valence ${displayNumber(x.raw)} (${escapeHtml(x.scale)})`
    + `<br>arousal ${displayNumber(y.raw)} (${escapeHtml(y.scale)})`
    + `<br>${escapeHtml(z.label)} ${displayNumber(z.raw)} (${escapeHtml(z.scale)})<br>${mood}`;
}

export function linkLabel(link) {
  return escapeHtml(`score ${displayNumber(link.score)}; ${link.explanation || ''}; groups ${link.supportedGroupCount || 0}`);
}

function nativeRange(range) {
  const endpoints = Array.isArray(range) ? range
    : (range && Number.isFinite(range.min) && Number.isFinite(range.max) ? [range.min, range.max] : null);
  return endpoints ? `${displayNumber(endpoints[0])} to ${displayNumber(endpoints[1])}` : 'no positioned values';
}

function escapeHtml(value) {
  return String(value).replace(/[&<>'"]/g, character => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;'}[character]));
}

// #243: dimmed colours for what lies outside the selected track's neighbourhood. The graph scales node opacity by the
// colour's alpha, and link opacity comes from each link's colour.
const DIMMED_NODE_COLOR = 'rgba(120,135,160,0.1)';
const DIMMED_LINK_COLOR = 'rgba(240,240,240,0.03)';

// The graph hands links back with their ends replaced by the nodes they join; either form names a track.
function linkEndTrackId(end) {
  return end && typeof end === 'object' ? end.id : end;
}

function linkEnds(link) {
  return {source: linkEndTrackId(link.source), target: linkEndTrackId(link.target)};
}

export function graphNeighbourFocus(visible, selectedTrackId) {
  return neighbourFocus({trackIds: visible.nodes.map(node => node.id), links: visible.links.map(linkEnds)}, selectedTrackId);
}

// Where the shown tracks linked to a track are placed (#267), so the camera can keep them all in view.
export function graphNeighbourPositions(visible, trackId) {
  const {neighbourIds} = graphNeighbourFocus(visible, trackId);
  return visible.nodes.filter(node => neighbourIds.has(node.id)).map(node => ({x: node.fx, y: node.fy, z: node.fz}));
}

export function focusedNodeColor(focus) {
  return node => (isFocusedTrack(focus, node.id) ? node.color : DIMMED_NODE_COLOR);
}

export function focusedLinkColor(focus) {
  return link => (isFocusedLink(focus, linkEnds(link)) ? relatednessLinkColor(link) : DIMMED_LINK_COLOR);
}
