// What the playlist preview shows for each preview event (#138): one row per track, with the step into it,
// and the energy chart: the arc's target and the energy each track reaches, left to right.

import {displayDuration} from '../../domain/display-duration.js';
import {displayNumber} from '../../domain/display-number.js';
import {trackPlaybackViewModel} from './track-playback-presenter.js';

const UNKNOWN = '—';
export const ENERGY_CHART = Object.freeze({width: 300, height: 80, padding: 8});
const KEY_STEPS = Object.freeze({true: 'Key compatible', false: 'Key clash', null: 'Key unknown'});

const PREVIEW_EVENT_VIEWS = Object.freeze({
  'playlist-preview-started': () => ({previewDisabled: true, status: {text: 'Previewing the playlist…', urgent: false}}),
  'playlist-previewed': event => ({previewDisabled: false, status: {text: previewSummary(event.preview), urgent: false},
    rows: previewRows(event.preview), chart: playlistEnergyChart(event.preview.tracks)}),
  'playlist-preview-failed': event => ({previewDisabled: false,
    status: {text: `Preview failed: ${event.message}`, urgent: true}, rows: [], chart: playlistEnergyChart([])}),
});

export function playlistPreviewViewModel() {
  return {previewDisabled: false, status: {text: '', urgent: false}, rows: [], chart: playlistEnergyChart([]),
    playback: trackPlaybackViewModel()};
}

// Preview waits until the recipe is complete, saying what it still needs; the missing controls are flagged (#234).
export function playlistReadinessViewModel(gaps) {
  const reasons = gaps.map(gap => gap.reason.charAt(0).toLowerCase() + gap.reason.slice(1));
  return {readiness: {ready: !gaps.length, reason: gaps.length ? `To preview: ${reasons.join(', ')}.` : ''},
    missing: gaps.map(gap => gap.control)};
}

export function presentPlaylistPreviewEvent(event) {
  return PREVIEW_EVENT_VIEWS[event.type](event);
}

export function playlistEnergyChart(tracks) {
  return {...ENERGY_CHART, level: energyLine(tracks, 'energyLevel'), target: energyLine(tracks, 'energyTarget'),
    label: tracks.length ? `Energy across ${trackCount(tracks.length)}: the arc target (dashed) and the energy each track reaches (solid).`
      : 'No energy to chart yet.'};
}

// A line through the known values, broken where a value is unknown.
function energyLine(tracks, field) {
  const segments = [];
  let segment = null;
  tracks.forEach((track, place) => {
    if (track[field] === null) { segment = null; return; }
    if (!segment) segments.push(segment = []);
    segment.push([chartX(place, tracks.length), chartY(track[field])]);
  });
  return segments;
}

function chartX(place, total) {
  const {width, padding} = ENERGY_CHART;
  return total === 1 ? width / 2 : padding + place * (width - 2 * padding) / (total - 1);
}

function chartY(energy) {
  const {height, padding} = ENERGY_CHART;
  return height - padding - energy * (height - 2 * padding);
}

function trackCount(count) {
  return count === 1 ? '1 track' : `${count} tracks`;
}

function previewSummary({tracks, warning}) {
  const summary = `${trackCount(tracks.length)} · ${previewedLength(tracks)}.`;
  return warning ? `${summary} Warning: ${warning}` : summary;
}

// The playlist's length (#257): the known lengths added up, saying how many tracks' lengths are unknown.
function previewedLength(tracks) {
  const known = tracks.map(track => track.durationSeconds).filter(seconds => displayDuration(seconds) !== null);
  if (!known.length) return 'length unknown';
  const total = displayDuration(known.reduce((sum, seconds) => sum + seconds, 0));
  const unknown = tracks.length - known.length;
  return unknown ? `${total}, plus ${unknown} of unknown length` : total;
}

function previewRows({tracks, transitions}) {
  const stepInto = new Map(transitions.map(step => [step.toTrackId, step]));
  return tracks.map((track, place) => ({
    trackId: track.trackId,
    place: String(place + 1),
    track: trackName(track),
    length: displayDuration(track.durationSeconds) ?? UNKNOWN,
    bpm: displayNumber(track.bpm),
    key: track.key ?? UNKNOWN,
    energy: shownNumber(track.energyLevel),
    target: shownNumber(track.energyTarget),
    transition: place === 0 ? 'Start' : stepText(stepInto.get(track.trackId)),
  }));
}

function trackName({artist, title}) {
  return [artist, title].filter(Boolean).join(' – ') || 'Untitled track';
}

function stepText(step) {
  if (!step) return UNKNOWN;
  return `${KEY_STEPS[step.keyCompatible]}, ${bpmStepText(step)}`;
}

function bpmStepText({bpmChange, bpmStepSmooth}) {
  if (bpmChange === null) return 'BPM change unknown';
  const change = `${bpmChange > 0 ? '+' : ''}${displayNumber(bpmChange)} BPM`;
  return bpmStepSmooth === false ? `${change} jump` : change;
}

function shownNumber(value) {
  return value === null ? UNKNOWN : displayNumber(value);
}
