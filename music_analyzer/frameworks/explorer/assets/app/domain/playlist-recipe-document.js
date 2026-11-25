// The drafted playlist as a version 1 recipe file (#139), which `music-analyzer playlist-recipe save` checks and stores,
// and a saved recipe back as a draft and its start track.
// Entered text becomes numbers here; the ranges are the analyzer's to check, with its own messages.

import {ARC_SHAPES} from './energy-arc-chain.js';
import {EMPTY_PLAYLIST_DRAFT, arcsSetTheLength} from './playlist-draft.js';
import {DEFAULT_MINIMUM_KEY_STRENGTH, DEFAULT_TRACK_COUNT} from './playlist-recipe.js';

const RECIPE_FORMAT = 'playlist-recipe';
// Version 2 (#265): arc energy ranges are raw arousal, as the graph shows it.
const RECIPE_VERSION = 2;

export class PlaylistRecipeDocumentError extends Error {}

export function playlistRecipeDocument(draft, startTrackId) {
  if (!startTrackId) refuseRecipe('Select a start track first');
  const document = {format: RECIPE_FORMAT, version: RECIPE_VERSION, start_track_id: startTrackId,
    bpm: {min: recipeNumber(draft.bpmMin, 'Min BPM'), max: recipeNumber(draft.bpmMax, 'Max BPM')}};
  if (!arcsSetTheLength(draft)) document.length = recipeLength(draft);
  return {...document,
    harmonic_mixing: {enabled: draft.harmonicMixing,
      minimum_key_strength: recipeNumber(enteredText(draft.minimumKeyStrength) || DEFAULT_MINIMUM_KEY_STRENGTH, 'Min key strength')},
    energy_plan: recipeEnergyPlan(draft),
    mood_hold: draft.moodHold || null};
}

// The server sends recipes in their canonical form; this checks only what the draft needs.
export function playlistDraftOfRecipe(document) {
  if (document?.format !== RECIPE_FORMAT) refuseRecipe('This is not a playlist recipe');
  if (document.version !== RECIPE_VERSION) {
    refuseRecipe(`Recipe version ${document.version} is not supported; only version ${RECIPE_VERSION} can be read`);
  }
  const arcs = document.energy_plan ?? [];
  const unit = arcs.some(arc => arc.minutes != null) ? 'minutes' : 'tracks';
  const length = document.length ?? {};
  const harmonic = document.harmonic_mixing ?? {};
  return {startTrackId: document.start_track_id, draft: Object.freeze({...EMPTY_PLAYLIST_DRAFT,
    bpmMin: savedNumber(document.bpm?.min, 'bpm.min'), bpmMax: savedNumber(document.bpm?.max, 'bpm.max'),
    count: length.tracks == null ? EMPTY_PLAYLIST_DRAFT.count : savedNumber(length.tracks, 'length.tracks'),
    durationMinutes: optionalSavedNumber(length.minutes, 'length.minutes'),
    harmonicMixing: harmonic.enabled !== false,
    minimumKeyStrength: harmonic.minimum_key_strength == null ? EMPTY_PLAYLIST_DRAFT.minimumKeyStrength
      : savedNumber(harmonic.minimum_key_strength, 'harmonic_mixing.minimum_key_strength'),
    arcLengthUnit: unit,
    energyArcs: Object.freeze(arcs.map((arc, place) => savedArc(arc, unit, `arc ${place + 1}`))),
    moodHold: document.mood_hold ?? ''})};
}

function savedArc(arc, unit, label) {
  if (!ARC_SHAPES.includes(arc?.shape)) refuseRecipe(`The recipe's ${label} shape is not one the panel offers`);
  return Object.freeze({shape: arc.shape, length: optionalSavedNumber(arc[unit], `${label} length`),
    low: optionalSavedNumber(arc.energy_low, `${label} energy_low`), high: optionalSavedNumber(arc.energy_high, `${label} energy_high`)});
}

function optionalSavedNumber(value, label) {
  return value == null ? '' : savedNumber(value, label);
}

function savedNumber(value, label) {
  if (typeof value !== 'number' || !Number.isFinite(value)) refuseRecipe(`The recipe's ${label} must be a number`);
  return String(value);
}

function recipeLength(draft) {
  if (draft.energyArcs.length > 1) refuseRecipe('Each arc in a chain needs a length');
  const minutes = enteredText(draft.durationMinutes);
  if (minutes) return {minutes: recipeNumber(minutes, 'Duration')};
  return {tracks: wholeRecipeNumber(enteredText(draft.count) || DEFAULT_TRACK_COUNT, 'Track count must be a whole number')};
}

function recipeEnergyPlan(draft) {
  const chained = arcsSetTheLength(draft);
  return draft.energyArcs.map((arc, place) => {
    const label = `Arc ${place + 1}`;
    const length = chained ? recipeArcLength(arc, draft.arcLengthUnit, label) : {};
    return {shape: arc.shape, ...length, energy_low: optionalRecipeNumber(arc.low, `${label} low energy`),
      energy_high: optionalRecipeNumber(arc.high, `${label} high energy`)};
  });
}

function recipeArcLength(arc, unit, label) {
  const length = enteredText(arc.length);
  if (!length) refuseRecipe('Each arc in a chain needs a length');
  if (unit === 'tracks') return {tracks: wholeRecipeNumber(length, `${label} length must be a whole number of tracks`)};
  return {minutes: recipeNumber(length, `${label} length`)};
}

function optionalRecipeNumber(value, label) {
  return enteredText(value) ? recipeNumber(value, label) : null;
}

function wholeRecipeNumber(value, message) {
  const parsed = parsedRecipeNumber(value);
  if (!Number.isInteger(parsed)) refuseRecipe(message);
  return parsed;
}

function recipeNumber(value, label) {
  const parsed = parsedRecipeNumber(value);
  if (parsed === null) refuseRecipe(`${label} must be a number`);
  return parsed;
}

function parsedRecipeNumber(value) {
  const text = enteredText(value);
  const parsed = Number(text);
  return text && Number.isFinite(parsed) ? parsed : null;
}

function enteredText(value) {
  return String(value ?? '').trim();
}

function refuseRecipe(message) {
  throw new PlaylistRecipeDocumentError(message);
}
