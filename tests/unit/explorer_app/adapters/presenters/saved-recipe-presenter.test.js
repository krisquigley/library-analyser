// Issue #139: what the saved recipe controls show for each event.
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {presentRejectedSavedRecipeInput, presentSavedRecipeEvent, savedRecipesViewModel} from '../../../../../music_explorer/frameworks/explorer/assets/app/adapters/presenters/saved-recipe-presenter.js';

test('before listing, only Saved recipes is offered', () => {
  assert.deepEqual(savedRecipesViewModel(), {busy: false, choices: null, status: {text: '', urgent: false}});
});

test('while listing or loading the controls are busy and say so', () => {
  assert.deepEqual(presentSavedRecipeEvent({type: 'saved-recipes-listing'}),
    {busy: true, status: {text: 'Reading saved recipes…', urgent: false}});
  assert.deepEqual(presentSavedRecipeEvent({type: 'saved-recipe-loading', name: 'Warm-up'}),
    {busy: true, status: {text: 'Loading Warm-up…', urgent: false}});
});

test('listed recipes are choices; one that cannot load is disabled and says why', () => {
  const view = presentSavedRecipeEvent({type: 'saved-recipes-listed', recipes: [
    {name: 'Warm-up', updatedAt: '2026-11-20T10:00:00Z', problem: null},
    {name: 'Old', updatedAt: '2026-11-01T09:00:00Z', problem: 'Its start track t is not an available track'}]});
  assert.deepEqual(view, {busy: false, status: {text: '2 saved recipes.', urgent: false}, choices: [
    {value: 'Warm-up', label: 'Warm-up (saved 2026-11-20)', disabled: false, title: ''},
    {value: 'Old', label: 'Old (cannot load)', disabled: true, title: 'Its start track t is not an available track'}]});
  assert.equal(presentSavedRecipeEvent({type: 'saved-recipes-listed', recipes: []}).status.text,
    'No saved recipes. Export one and save it with music-analyzer playlist-recipe save.');
});

test('a loaded recipe and a failure are told', () => {
  assert.deepEqual(presentSavedRecipeEvent({type: 'saved-recipe-loaded', name: 'Warm-up', startTrackId: 't', draft: {}}),
    {busy: false, status: {text: 'Loaded Warm-up.', urgent: false}});
  assert.deepEqual(presentSavedRecipeEvent({type: 'saved-recipe-failed', message: 'No saved recipe named "x"'}),
    {busy: false, status: {text: 'Saved recipe failed: No saved recipe named "x"', urgent: true}});
});

test('input the controls rejected is an alert', () => {
  assert.deepEqual(presentRejectedSavedRecipeInput('Choose a saved recipe to load'),
    {status: {text: 'Choose a saved recipe to load', urgent: true}});
});
