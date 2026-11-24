// Issue #258: listening to a track from the playlist preview. A command asks the player; what the player reports
// moves the playback on and is published, and a report about a track no longer asked for is ignored.
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {createTrackPlayback} from '../../../../../music_explorer/frameworks/explorer/assets/app/application/listen-to-track/listen-to-track.js';
import {TRACK_PLAYBACK_EVENT_TYPES} from '../../../../../music_explorer/frameworks/explorer/assets/app/application/listen-to-track/track-playback-events.js';

function playback() {
  const asked = [];
  const published = [];
  const trackPlayer = Object.fromEntries(['load', 'pause', 'resume', 'stop'].map(operation =>
    [operation, (...args) => asked.push([operation, ...args])]));
  const eventBus = {publish: event => published.push(event), subscribe() {}};
  return {use: createTrackPlayback({trackPlayer, eventBus}), asked, published};
}

test('playing a track loads it, and the player saying it plays is published', () => {
  const {use, asked, published} = playback();
  use.toggle('a');
  use.heard({kind: 'playing', trackId: 'a'});
  assert.deepEqual(asked, [['load', 'a']]);
  assert.deepEqual(published, [{type: 'track-playback-loading', trackId: 'a'}, {type: 'track-playback-playing', trackId: 'a'}]);
  assert.equal(use.state(), 'playing');
});

test("the same track's button pauses it and plays it on", () => {
  const {use, asked} = playback();
  use.toggle('a');
  use.heard({kind: 'playing', trackId: 'a'});
  use.toggle('a');
  use.heard({kind: 'paused', trackId: 'a'});
  use.toggle('a');
  assert.deepEqual(asked, [['load', 'a'], ['pause'], ['resume']]);
});

test('another track replaces the one playing, and late reports about the first are ignored', () => {
  const {use, asked, published} = playback();
  use.toggle('a');
  use.heard({kind: 'playing', trackId: 'a'});
  use.toggle('b');
  use.heard({kind: 'paused', trackId: 'a'});
  assert.deepEqual(asked, [['load', 'a'], ['load', 'b']]);
  assert.deepEqual(published.at(-1), {type: 'track-playback-loading', trackId: 'b'});
  assert.equal(use.state(), 'loading');
});

test('an ending and a failure are published; a stop silences the player once', () => {
  const {use, asked, published} = playback();
  use.toggle('a');
  use.heard({kind: 'failed', trackId: 'a', message: 'missing'});
  assert.deepEqual(published.at(-1), {type: 'track-playback-failed', trackId: 'a', message: 'missing'});
  use.toggle('a');
  use.heard({kind: 'playing', trackId: 'a'});
  use.heard({kind: 'ended', trackId: 'a'});
  assert.deepEqual(published.at(-1), {type: 'track-playback-stopped', trackId: 'a'});
  use.stop();
  use.toggle('b');
  use.stop();
  use.stop();
  assert.deepEqual(asked.filter(([operation]) => operation === 'stop'), [['stop']]);
  assert.deepEqual(published.at(-1), {type: 'track-playback-stopped', trackId: 'b'});
});

test('a report the playback cannot take, such as playing after a stop, is ignored', () => {
  const {use, published} = playback();
  use.heard({kind: 'playing', trackId: null});
  assert.deepEqual([published, use.state()], [[], 'stopped']);
});

test('every playback event is declared', () => {
  assert.deepEqual(TRACK_PLAYBACK_EVENT_TYPES, ['track-playback-loading', 'track-playback-playing', 'track-playback-paused',
    'track-playback-stopped', 'track-playback-failed']);
});
