// Lengths shown to the listener (#236, #257): m:ss, or h:mm:ss from an hour; nothing for an unknown length.
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {displayDuration} from '../../../../music_explorer/frameworks/explorer/assets/app/domain/display-duration.js';

test('a length reads m:ss, or h:mm:ss from an hour, to the nearest second', () => {
  assert.deepEqual([displayDuration(225.4), displayDuration(59.6), displayDuration(3725)], ['3:45', '1:00', '1:02:05']);
});

test('an unknown or impossible length is not shown', () => {
  assert.deepEqual([null, undefined, 0, -3, Number.NaN, '180'].map(displayDuration), [null, null, null, null, null, null]);
});
