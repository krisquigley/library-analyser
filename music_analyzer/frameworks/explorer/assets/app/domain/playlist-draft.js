// The playlist the listener is drafting in the Download M3U controls (#146), with its chain of energy arcs (#137).
// Values stay as entered: the server owns the range rules and their messages.

import {addEnergyArc, editEnergyArc, moveEnergyArc, removeEnergyArc} from './energy-arc-chain.js';
import {playlistRecipe} from './playlist-recipe.js';

// One unit for every arc's length (#137, owner decision A): the chain is measured one way.
export const ARC_LENGTH_UNITS = Object.freeze(['tracks', 'minutes']);

export const EMPTY_PLAYLIST_DRAFT = Object.freeze({
  bpmMin: '', bpmMax: '', count: '10', durationMinutes: '', harmonicMixing: true, minimumKeyStrength: '0.5',
  arcLengthUnit: 'tracks', energyArcs: Object.freeze([]), moodHold: '',
});

export class PlaylistDraftError extends Error {}

export function editPlaylistDraft(draft, changes) {
  const unknown = Object.keys(changes).find(control => !Object.hasOwn(EMPTY_PLAYLIST_DRAFT, control) || control === 'energyArcs');
  if (unknown) throw new PlaylistDraftError(`Unknown playlist control: ${unknown}`);
  if (Object.hasOwn(changes, 'arcLengthUnit') && !ARC_LENGTH_UNITS.includes(changes.arcLengthUnit)) {
    throw new PlaylistDraftError('Arc lengths are in tracks or minutes');
  }
  return Object.freeze({...draft, ...changes});
}

export function addDraftArc(draft) {
  return withArcs(draft, addEnergyArc(draft.energyArcs));
}

export function removeDraftArc(draft, place) {
  return withArcs(draft, removeEnergyArc(draft.energyArcs, place));
}

export function moveDraftArc(draft, place, offset) {
  return withArcs(draft, moveEnergyArc(draft.energyArcs, place, offset));
}

export function editDraftArc(draft, place, changes) {
  return withArcs(draft, editEnergyArc(draft.energyArcs, place, changes));
}

export function minimumKeyStrengthApplies(draft) {
  return draft.harmonicMixing;
}

// Once an arc has a length, the arcs set the playlist's length and the track count and duration don't apply.
export function arcsSetTheLength(draft) {
  return draft.energyArcs.some(arc => String(arc.length).trim() !== '');
}

export function playlistRecipeOf(draft, startTrackId) {
  return playlistRecipe({
    startTrackId, bpmMin: draft.bpmMin, bpmMax: draft.bpmMax, count: draft.count,
    durationMinutes: draft.durationMinutes, harmonicMixing: draft.harmonicMixing,
    minimumKeyStrength: draft.minimumKeyStrength, energyArcs: draft.energyArcs, arcUnit: draft.arcLengthUnit,
    moodHold: draft.moodHold,
  });
}

function withArcs(draft, energyArcs) {
  return Object.freeze({...draft, energyArcs});
}
