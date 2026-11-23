// Issue #139: the saved recipe controls' commands; a chosen name is validated before the use case sees it.
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {savedRecipeController} from '../../../../../music_explorer/frameworks/explorer/assets/app/adapters/controllers/saved-recipe-controller.js';

function harness() {
  const calls = [];
  const rejected = [];
  const controller = savedRecipeController({savedRecipes: {list: async () => calls.push(['list']),
    load: async name => calls.push(['load', name])}, rejectInput: message => rejected.push(message)});
  return {controller, calls, rejected};
}

test('Saved recipes lists them, and Load loads the chosen name', async () => {
  const {controller, calls, rejected} = harness();
  await controller.listRequested();
  await controller.loadRequested('Warm-up');
  assert.deepEqual([calls, rejected], [[['list'], ['load', 'Warm-up']], []]);
});

test('Load without a chosen recipe is rejected with a message and loads nothing', async () => {
  const {controller, calls, rejected} = harness();
  for (const name of ['', '   ', undefined, 7]) await controller.loadRequested(name);
  assert.deepEqual(calls, []);
  assert.deepEqual(rejected, Array(4).fill('Choose a saved recipe to load'));
});
