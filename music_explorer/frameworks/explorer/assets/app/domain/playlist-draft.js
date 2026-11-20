// The playlist the listener is drafting in the Download M3U controls (#146).
// Values stay as entered: the server owns the range rules and their messages.

import {ARC_SHAPES, NEW_ENERGY_ARC} from './energy-arc-chain.js';
import {playlistRecipe} from './playlist-recipe.js';

export const ENERGY_ARC_SHAPES = Object.freeze(['none', ...ARC_SHAPES]);

export const EMPTY_PLAYLIST_DRAFT = Object.freeze({
  bpmMin: '', bpmMax: '', count: '10', durationMinutes: '', harmonicMixing: true, minimumKeyStrength: '0.5',
  energyArc: 'none', energyLow: '', energyHigh: '', moodHold: '',
});

export function editPlaylistDraft(draft, changes) {
  const unknown = Object.keys(changes).find(control => !Object.hasOwn(EMPTY_PLAYLIST_DRAFT, control));
  if (unknown) throw new Error(`Unknown playlist control: ${unknown}`);
  return Object.freeze({...draft, ...changes});
}

export function minimumKeyStrengthApplies(draft) {
  return draft.harmonicMixing;
}

export function energyRangeApplies(draft) {
  return draft.energyArc !== 'none';
}

export function playlistRecipeOf(draft, startTrackId) {
  return playlistRecipe({
    startTrackId, bpmMin: draft.bpmMin, bpmMax: draft.bpmMax, count: draft.count,
    durationMinutes: draft.durationMinutes, harmonicMixing: draft.harmonicMixing,
    minimumKeyStrength: draft.minimumKeyStrength, energyArcs: energyArcsOf(draft),
    moodHold: draft.moodHold,
  });
}

// The draft's one arc, without a length, spans the whole playlist.
function energyArcsOf(draft) {
  if (!energyRangeApplies(draft)) return [];
  return [{...NEW_ENERGY_ARC, shape: draft.energyArc, low: draft.energyLow, high: draft.energyHigh}];
}
