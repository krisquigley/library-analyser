// Issue #146: numbers shown to the listener, to one decimal place.
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {displayNumber} from '../../../../music_explorer/frameworks/explorer/assets/app/domain/display-number.js';

test('a finite number is rounded half away from zero to one decimal', () => {
  assert.deepEqual([0.25, -0.25, 1, 0.04, 123.456].map(displayNumber), ['0.3', '-0.3', '1.0', '0.0', '123.5']);
});

test('anything else is shown as it is', () => {
  assert.deepEqual([NaN, Infinity, null, undefined, 'n/a'].map(displayNumber), ['NaN', 'Infinity', 'null', 'undefined', 'n/a']);
});
