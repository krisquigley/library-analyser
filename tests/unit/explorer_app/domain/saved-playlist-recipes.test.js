// Issue #139: the lifecycle of the saved recipe list and of loading one, as a transitions table.
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {
  SAVED_RECIPE_STATES, SavedRecipeTransitionError, nextSavedRecipeState,
} from '../../../../music_explorer/frameworks/explorer/assets/app/domain/saved-playlist-recipes.js';

test('the states', () => {
  assert.deepEqual(SAVED_RECIPE_STATES, ['idle', 'listing', 'listed', 'loading', 'loaded', 'failed']);
});

test('listing and loading start from any settled state, and only the one in flight settles', () => {
  const legal = [
    ['idle', 'list', 'listing'], ['listed', 'list', 'listing'], ['loaded', 'list', 'listing'], ['failed', 'list', 'listing'],
    ['listing', 'succeed', 'listed'], ['listing', 'fail', 'failed'],
    ['listed', 'load', 'loading'], ['loaded', 'load', 'loading'], ['failed', 'load', 'loading'],
    ['loading', 'succeed', 'loaded'], ['loading', 'fail', 'failed'],
  ];
  for (const [state, action, next] of legal) assert.equal(nextSavedRecipeState(state, action), next, `${state} ${action}`);
});

test('an illegal transition is refused', () => {
  for (const [state, action] of [['idle', 'load'], ['idle', 'succeed'], ['listing', 'load'], ['loading', 'list'], ['listed', 'fail']]) {
    assert.throws(() => nextSavedRecipeState(state, action), SavedRecipeTransitionError, `${state} ${action}`);
  }
});
