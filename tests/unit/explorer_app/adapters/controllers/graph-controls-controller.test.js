// Issue #146: the mood tracker and graph filter controls' input, validated before the use case sees it.
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {graphControlsController} from '../../../../../music_explorer/frameworks/explorer/assets/app/adapters/controllers/graph-controls-controller.js';

function harness() {
  const calls = [];
  const rejected = [];
  const graphLoad = {
    chooseMood: async mood => calls.push(['chooseMood', mood]),
    editControls: changes => calls.push(['editControls', changes]),
    applyFilters: () => { calls.push(['applyFilters']); return true; },
    clearFilters: () => calls.push(['clearFilters']),
  };
  return {controller: graphControlsController({graphLoad, rejectInput: message => rejected.push(message)}), calls, rejected};
}

test('a chosen mood goes to the use case', async () => {
  const {controller, calls} = harness();
  await controller.moodChosen('heavy');
  assert.deepEqual(calls, [['chooseMood', 'heavy']]);
});

test('a BPM range becomes numbers, blank meaning unbounded, and is applied', () => {
  const {controller, calls} = harness();
  assert.equal(controller.bpmRangeEdited({bpmMin: ' 90 ', bpmMax: ''}), true);
  assert.deepEqual(calls, [['editControls', {bpmMin: 90, bpmMax: null}], ['applyFilters']]);
});

test('chosen genres are applied', () => {
  const {controller, calls} = harness();
  controller.genresEdited(['jazz', 'rock']);
  assert.deepEqual(calls, [['editControls', {genres: ['jazz', 'rock']}], ['applyFilters']]);
});

test('clearing the filters goes to the use case', () => {
  const {controller, calls} = harness();
  controller.filtersCleared();
  assert.deepEqual(calls, [['clearFilters']]);
});

test('invalid input is rejected with a message and never reaches the use case', () => {
  const cases = [
    [controller => controller.bpmRangeEdited({bpmMin: 'fast', bpmMax: ''}), 'Minimum BPM must be a number'],
    [controller => controller.bpmRangeEdited({bpmMin: '', bpmMax: 7}), 'Maximum BPM must be a number'],
    [controller => controller.genresEdited(['jazz', 3]), 'Genres must be a list of text'],
    [controller => controller.genresEdited('jazz'), 'Genres must be a list of text'],
    [controller => controller.moodChosen(null), 'Mood tracker score label must be text'],
  ];
  for (const [act, message] of cases) {
    const {controller, calls, rejected} = harness();
    act(controller);
    assert.deepEqual(calls, []);
    assert.deepEqual(rejected, [message]);
  }
});
