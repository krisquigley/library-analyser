// What the playlist preview shows for each preview event (#138): one row per track, with the step into it.

import {displayNumber} from '../../domain/display-number.js';

const UNKNOWN = '—';
const KEY_STEPS = Object.freeze({true: 'Key compatible', false: 'Key clash', null: 'Key unknown'});

const PREVIEW_EVENT_VIEWS = Object.freeze({
  'playlist-preview-started': () => ({previewDisabled: true, status: {text: 'Previewing the playlist…', urgent: false}}),
  'playlist-previewed': event => ({previewDisabled: false, status: {text: previewSummary(event.preview), urgent: false},
    rows: previewRows(event.preview)}),
  'playlist-preview-failed': event => ({previewDisabled: false,
    status: {text: `Preview failed: ${event.message}`, urgent: true}, rows: []}),
});

export function playlistPreviewViewModel() {
  return {previewDisabled: false, status: {text: '', urgent: false}, rows: []};
}

export function presentPlaylistPreviewEvent(event) {
  return PREVIEW_EVENT_VIEWS[event.type](event);
}

function previewSummary({tracks, warning}) {
  const count = tracks.length === 1 ? '1 track.' : `${tracks.length} tracks.`;
  return warning ? `${count} Warning: ${warning}` : count;
}

function previewRows({tracks, transitions}) {
  const stepInto = new Map(transitions.map(step => [step.toTrackId, step]));
  return tracks.map((track, place) => ({
    place: String(place + 1),
    track: `${track.artist} – ${track.title}`,
    bpm: displayNumber(track.bpm),
    key: track.camelot ?? track.key ?? UNKNOWN,
    energy: shownNumber(track.energyLevel),
    target: shownNumber(track.energyTarget),
    transition: place === 0 ? 'Start' : stepText(stepInto.get(track.trackId)),
  }));
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
