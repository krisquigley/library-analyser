// The drafted playlist as a version 1 recipe file (#139), which `music-analyzer playlist-recipe save` checks and stores.
// Entered text becomes numbers here; the ranges are the analyzer's to check, with its own messages.

import {arcsSetTheLength} from './playlist-draft.js';
import {DEFAULT_MINIMUM_KEY_STRENGTH, DEFAULT_TRACK_COUNT} from './playlist-recipe.js';

const RECIPE_FORMAT = 'playlist-recipe';
const RECIPE_VERSION = 1;

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
