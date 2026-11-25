// Issue #271: how a neighbour differs from the selected track on each axis, as a share of the library's span.
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {axisSpans, differenceShares} from '../../../../music_explorer/frameworks/explorer/assets/app/domain/neighbour-difference.js';

const track = (valence, arousal, bpm) => ({valence, arousal, bpm});

test("the library's span on each axis runs from its lowest to its highest value", () => {
  assert.deepEqual(axisSpans([track(0.25, 0.5, 120), track(0.75, 0.25, 90), track(0.5, 1, 130)]),
    {valence: 0.5, arousal: 0.75, bpm: 40});
});

test('values that are not numbers take no part in a span, and an axis with fewer than two has none', () => {
  assert.deepEqual(axisSpans([track(0.25, "x", 120), track(0.75, null, NaN)]), {valence: 0.5, arousal: 0, bpm: 0});
  assert.deepEqual(axisSpans([]), {valence: 0, arousal: 0, bpm: 0});
});

test("each share is the difference's size over the library span, whichever track is higher", () => {
  const spans = {valence: 0.4, arousal: 0.5, bpm: 40};
  const shares = differenceShares(track(0.2, 0.5, 120), track(0.3, 0.25, 130), spans);
  assert.deepEqual(Object.keys(shares), ['valence', 'arousal', 'bpm']);
  for (const [axis, share] of Object.entries({valence: 0.25, arousal: 0.5, bpm: 0.25})) {
    assert.ok(Math.abs(shares[axis] - share) < 1e-9, axis);
  }
  assert.deepEqual(differenceShares(track(0.3, 0.25, 130), track(0.2, 0.5, 120), spans), shares);
});

test('an axis without a span or without both values shows no difference', () => {
  assert.deepEqual(differenceShares(track(0.2, null, 120), track(0.3, 0.25, 130), {valence: 0, arousal: 0.5, bpm: 40}),
    {valence: 0, arousal: 0, bpm: 0.25});
});
