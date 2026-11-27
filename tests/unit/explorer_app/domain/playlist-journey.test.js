// Issue #294: the hand-built playlist's journey over time: each track spans its length, with its BPM, key, arousal and
// valence.
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {JOURNEY_MEASURES, playlistJourney} from '../../../../music_explorer/frameworks/explorer/assets/app/domain/playlist-journey.js';

const track = (trackId, fields = {}) => ({trackId, bpm: 120, camelot: '8A', arousal: 4, valence: 5, durationSeconds: 100,
  ...fields});

test('the measures are BPM, key, arousal and valence, in that order', () => {
  assert.deepEqual(JOURNEY_MEASURES, ['bpm', 'key', 'arousal', 'valence']);
});

test("each track spans its length in the listener's order; its key is its Camelot number; unknown values are gaps", () => {
  const journey = playlistJourney(['b', 'a'], [track('a', {camelot: null, valence: null}), track('b', {bpm: 124, camelot: '12B',
    durationSeconds: 60})]);
  assert.deepEqual(journey.stops.map(stop => [stop.track.trackId, stop.start, stop.end]), [['b', 0, 60], ['a', 60, 160]]);
  assert.deepEqual([journey.lengthSeconds, journey.lengthsEstimated], [160, false]);
  assert.deepEqual(journey.measures, {
    bpm: [{start: 0, end: 60, value: 124}, {start: 60, end: 160, value: 120}],
    key: [{start: 0, end: 60, value: 12}, {start: 60, end: 160, value: null}],
    arousal: [{start: 0, end: 60, value: 4}, {start: 60, end: 160, value: 4}],
    valence: [{start: 0, end: 60, value: 5}, {start: 60, end: 160, value: null}],
  });
});

test('a track the preview has not seen yet is left out until it has', () => {
  assert.deepEqual(playlistJourney(['a', 'new', 'b'], [track('a'), track('b')]).stops.map(stop => stop.track.trackId), ['a', 'b']);
});

test('a track of unknown length spans the average of the known ones, or three minutes, and the journey says so', () => {
  const some = playlistJourney(['a', 'b', 'c'], [track('a', {durationSeconds: 100}), track('b', {durationSeconds: null}),
    track('c', {durationSeconds: 200})]);
  assert.deepEqual([some.stops.map(stop => stop.end), some.lengthsEstimated], [[100, 250, 450], true]);
  const none = playlistJourney(['a'], [track('a', {durationSeconds: null})]);
  assert.deepEqual([none.lengthSeconds, none.lengthsEstimated], [180, true]);
});

test('a Camelot code that is not one reads as an unknown key', () => {
  const journey = playlistJourney(['a', 'b'], [track('a', {camelot: '13A'}), track('b', {camelot: 'C major'})]);
  assert.deepEqual(journey.measures.key.map(step => step.value), [null, null]);
});
