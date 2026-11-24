// What the Download M3U controls and the energy arc editor show for the draft and each download event (#146, #137).

import {arcsSetTheLength, minimumKeyStrengthApplies} from '../../domain/playlist-draft.js';

const ARC_SHAPE_CHOICES = Object.freeze([
  ['steady', 'Steady energy'], ['rise', 'Rising energy'], ['fall', 'Falling energy'],
  ['peak', 'Energy peak'], ['dip', 'Energy dip']]);
const ARC_LENGTH_UNIT_CHOICES = Object.freeze([['tracks', 'Tracks'], ['minutes', 'Minutes']]);

const PLAYLIST_EVENT_VIEWS = Object.freeze({
  'playlist-draft-edited': event => draftView(event.draft),
  'playlist-download-started': () => ({downloadDisabled: true}),
  'playlist-downloaded': event => ({downloadDisabled: false, status: {
    text: event.warning ? `M3U downloaded. Warning: ${event.warning}` : 'M3U downloaded.', urgent: false}}),
  'playlist-download-failed': event => ({downloadDisabled: false, status: {
    text: `M3U download failed: ${event.message}`, urgent: true}}),
});

export function playlistControlsViewModel({draft, downloadState, moods}) {
  return {
    values: draft,
    ...draftView(draft),
    downloadDisabled: downloadState === 'downloading',
    arcShapeChoices: ARC_SHAPE_CHOICES.map(choice => [...choice]),
    arcLengthUnitChoices: ARC_LENGTH_UNIT_CHOICES.map(choice => [...choice]),
    moodChoices: [['', 'No mood hold'], ...moods.map(mood => [mood, `Hold mood: ${mood}`])],
  };
}

export function presentPlaylistDownloadEvent(event) {
  return PLAYLIST_EVENT_VIEWS[event.type](event);
}

// A draft that replaced the one in the controls, such as a loaded saved recipe (#139): its values are shown too.
export function presentLoadedPlaylistDraft(draft) {
  return {values: draft, ...draftView(draft)};
}

export function presentRejectedPlaylistInput(message) {
  return {status: {text: message, urgent: true}};
}

function draftView(draft) {
  return {
    minimumKeyStrengthDisabled: !minimumKeyStrengthApplies(draft),
    arcs: draft.energyArcs.map((arc, place) => arcRow(arc, place, draft)),
    arcLengthPlaceholder: draft.arcLengthUnit,
    lengthDisabled: arcsSetTheLength(draft),
  };
}

function arcRow({shape, length, low, high}, place, draft) {
  return {shape, length, low, high, canMoveEarlier: place > 0, canMoveLater: place < draft.energyArcs.length - 1,
    summary: [`Arc ${place + 1}`, arcShapeCaption(shape), arcLengthSummary(length, draft.arcLengthUnit), arcRangeSummary(low, high)].join(' · ')};
}

function arcShapeCaption(shape) {
  return (ARC_SHAPE_CHOICES.find(([value]) => value === shape) || [shape, shape])[1];
}

function arcLengthSummary(length, unit) {
  if (length === '') return 'length not set';
  return `${length} ${Number(length) === 1 ? unit.replace(/s$/, '') : unit}`;
}

function arcRangeSummary(low, high) {
  if (low !== '' && high !== '') return `energy ${low} to ${high}`;
  if (low !== '') return `energy from ${low}`;
  if (high !== '') return `energy up to ${high}`;
  return 'default energy range';
}
