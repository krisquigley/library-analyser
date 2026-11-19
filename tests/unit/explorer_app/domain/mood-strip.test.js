// Issue #146: which tracks the mood strip marks, and in what order.
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {moodStripMarks} from '../../../../music_explorer/frameworks/explorer/assets/app/domain/mood-strip.js';

const node = (id, raw, label = 'calm') => ({id, label: id.toUpperCase(), moodScore: raw == null ? null : {label, raw}});

test('every track with a selected mood score is marked at its raw score, lowest first, ties by id', () => {
  const marks = moodStripMarks([node('z', 0.6), node('b', 0), node('a', 0.6), node('top', 1), node('missing', null)], 'a');
  assert.deepEqual(marks.map(mark => [mark.id, mark.score, mark.position, mark.selected]),
    [['b', 0, 0, false], ['a', 0.6, 0.6, true], ['z', 0.6, 0.6, false], ['top', 1, 1, false]]);
  assert.deepEqual(marks[1], {id: 'a', label: 'A', moodLabel: 'calm', score: 0.6, position: 0.6, selected: true});
});

test('with no scored tracks there are no marks', () => {
  assert.deepEqual(moodStripMarks([node('a', null)], 'a'), []);
});
