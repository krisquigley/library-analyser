// What the 3D graph shows beside its nodes (#146): the axes, the colour and link legends, and hover labels.

import {displayNumber} from '../../domain/display-number.js';
import {axisSpans, differenceShares} from '../../domain/neighbour-difference.js';
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
  return Math.round((0.18 + relatednessStrength(link && link.score) * 0.54) * 100) / 100;
}

function relatednessStrength(score) {
  const number = Number(score);
  return Number.isFinite(number) ? Math.max(0, Math.min(1, number)) : 0;
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

// #273: the selection's links show how each neighbour differs from it. The hue runs blue, through purple, to red as the
// neighbour's valence is lower or higher, as the track colours do; the link is more vivid the further apart the two are in
// arousal and BPM, never so pale its hue is lost; and it is as thick as the tracks are related.
const FULL_DIFFERENCE = 0.25;
const LOWER_VALENCE_HUE = 220;
const SAME_VALENCE_HUE = 290;
const PALEST = 0.25;
const SELECTED_LINK_LIGHTNESS = 0.6;
const SELECTED_LINK_ALPHA = 0.9;
const SELECTED_LINK_THICKENING = 4;

export function focusedLinkColor(focus, libraryNodes) {
  if (!focus.active) return relatednessLinkColor;
  const tracks = new Map(libraryNodes.map(node => [node.id, differenceTrack(node)]));
  const spans = axisSpans([...tracks.values()]);
  const selected = tracks.get(focus.selectedTrackId);
  return link => {
    const {source, target} = linkEnds(link);
    if (!isFocusedLink(focus, {source, target})) return DIMMED_LINK_COLOR;
    const neighbour = tracks.get(source === focus.selectedTrackId ? target : source);
    if (!selected || !neighbour) return relatednessLinkColor(link);
    return neighbourDifferenceColor(differenceShares(selected, neighbour, spans));
  };
}

export function neighbourDifferenceColor({valence, arousal, bpm}) {
  const towardsHigher = Math.max(-1, Math.min(1, valence / FULL_DIFFERENCE));
  const hue = SAME_VALENCE_HUE + (SAME_VALENCE_HUE - LOWER_VALENCE_HUE) * towardsHigher;
  const apart = Math.min(1, (Math.abs(arousal) + Math.abs(bpm)) / 2 / FULL_DIFFERENCE);
  const [red, green, blue] = hslChannels(hue, PALEST + (1 - PALEST) * apart, SELECTED_LINK_LIGHTNESS);
  return `rgba(${red},${green},${blue},${SELECTED_LINK_ALPHA})`;
}

export function relatednessLinkWidth(link) {
  return 1 + relatednessStrength(link && link.score);
}

export function focusedLinkWidth(focus) {
  return link => (focus.active && isFocusedLink(focus, linkEnds(link))
    ? 1 + SELECTED_LINK_THICKENING * relatednessStrength(link.score) : relatednessLinkWidth(link));
}

function hslChannels(hue, saturation, lightness) {
  const chroma = (1 - Math.abs(2 * lightness - 1)) * saturation;
  const channel = offset => {
    const turn = (offset + hue / 30) % 12;
    return Math.round((lightness - chroma / 2 * Math.max(-1, Math.min(turn - 3, 9 - turn, 1))) * 255);
  };
  return [channel(0), channel(8), channel(4)];
}

function differenceTrack(node) {
  const axis = node.axis || {};
  return {valence: axis.x?.raw, arousal: axis.y?.raw, bpm: axis.z?.raw};
}
