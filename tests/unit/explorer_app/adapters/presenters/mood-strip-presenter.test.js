// Issue #146: how the mood strip lays out its marks and what its readout says.
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {moodMarkDescription, moodStripViewModel, nearestMarkIndex} from '../../../../../music_explorer/frameworks/explorer/assets/app/adapters/presenters/mood-strip-presenter.js';

const mark = (id, position, selected = false) => ({id, label: id, moodLabel: 'calm', score: position, position, selected});

test('a mark says its track, mood and raw score', () => {
  assert.equal(moodMarkDescription(mark('a', 0.123456)), 'a: calm 0.1 / 1 (raw sigmoid mean score)');
});

test('marks spread across the padded width, and ties stack alternately above and below the line', () => {
  const view = moodStripViewModel([mark('a', 0), mark('b', 0.5), mark('c', 0.5), mark('d', 0.5), mark('e', 1)], 128);
  assert.deepEqual([view.width, view.height, view.baseline, view.padding], [128, 70, 35, 14]);
  assert.deepEqual(view.marks.map(m => [m.x, m.y]), [[14, 30], [64, 30], [64, 40], [64, 25], [114, 30]]);
});

test('the picker starts on the selected track, or the first, and reads out each mark', () => {
  const view = moodStripViewModel([mark('a', 0.2), mark('b', 0.4, true)], 600);
  assert.deepEqual([view.pickerMax, view.disabled, view.index], [1, false, 1]);
  assert.equal(view.readouts[1], '2 / 2: b: calm 0.4 / 1 (raw sigmoid mean score)');
  assert.equal(moodStripViewModel([mark('a', 0.2)], 600).index, 0);
});

test('an empty strip says why, its picker is disabled, and an unmeasured canvas is 600 wide', () => {
  const view = moodStripViewModel([], 0);
  assert.deepEqual([view.width, view.marks, view.pickerMax, view.disabled, view.index], [600, [], 0, true, 0]);
  assert.equal(view.emptyReadout, 'No visible tracks have this selected mood score; tracks without it have no mark.');
});

test('a click picks the nearest mark, the first of equals', () => {
  const view = moodStripViewModel([mark('a', 0), mark('b', 0.5), mark('c', 1)], 128);
  assert.deepEqual([nearestMarkIndex(view, 0), nearestMarkIndex(view, 70), nearestMarkIndex(view, 89), nearestMarkIndex(view, 500)], [0, 1, 1, 2]);
});
