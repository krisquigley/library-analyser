// Issue #278: the playlist the listener builds by hand from the graph's labels.
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {
  EMPTY_HAND_BUILT_PLAYLIST, HandBuiltPlaylistError, MOST_HAND_BUILT_TRACKS, addNeighbour, handBuiltPlaylistOf, removeTrack,
} from '../../../../music_explorer/frameworks/explorer/assets/app/domain/hand-built-playlist.js';

test('the first + starts the playlist with the selected track, then the neighbour', () => {
  assert.deepEqual(addNeighbour(EMPTY_HAND_BUILT_PLAYLIST, {selectedTrackId: 'a', neighbourId: 'b'}), ['a', 'b']);
});

test('each later + adds the neighbour after the tracks already in it', () => {
  assert.deepEqual(addNeighbour(['a', 'b'], {selectedTrackId: 'b', neighbourId: 'c'}), ['a', 'b', 'c']);
});

test('a selected track the listener reached another way joins the playlist before its neighbour', () => {
  assert.deepEqual(addNeighbour(['a', 'b'], {selectedTrackId: 'x', neighbourId: 'c'}), ['a', 'b', 'x', 'c']);
});

test('a track already in the playlist is never added twice', () => {
  const playlist = Object.freeze(['a', 'b', 'c']);
  assert.equal(addNeighbour(playlist, {selectedTrackId: 'c', neighbourId: 'a'}), playlist);
  assert.deepEqual(addNeighbour(['a', 'b'], {selectedTrackId: 'x', neighbourId: 'a'}), ['a', 'b', 'x']);
});

test('the playlist is frozen, and refuses to grow past its limit', () => {
  const full = Object.freeze(Array.from({length: MOST_HAND_BUILT_TRACKS - 1}, (_, place) => `t${place}`));
  const fuller = addNeighbour(full, {selectedTrackId: 't0', neighbourId: 'last'});
  assert.equal(fuller.length, MOST_HAND_BUILT_TRACKS);
  assert.ok(Object.isFrozen(fuller));
  assert.throws(() => addNeighbour(fuller, {selectedTrackId: 't0', neighbourId: 'more'}),
    new HandBuiltPlaylistError(`A playlist holds at most ${MOST_HAND_BUILT_TRACKS} tracks`));
  assert.throws(() => addNeighbour(full, {selectedTrackId: 'x', neighbourId: 'y'}), HandBuiltPlaylistError);
  assert.equal(MOST_HAND_BUILT_TRACKS, 500);
});

test('a track is removed from wherever it is', () => {
  assert.deepEqual(removeTrack(['a', 'b', 'c'], 'b'), ['a', 'c']);
  assert.deepEqual(removeTrack(['a'], 'gone'), ['a']);
});

test('a kept playlist is read only when it is a list of distinct track IDs within the limit', () => {
  assert.deepEqual(handBuiltPlaylistOf(['a', 'b']), ['a', 'b']);
  assert.ok(Object.isFrozen(handBuiltPlaylistOf(['a'])));
  assert.equal(handBuiltPlaylistOf(null), EMPTY_HAND_BUILT_PLAYLIST, 'nothing kept yet');
  const tooMany = Array.from({length: MOST_HAND_BUILT_TRACKS + 1}, (_, place) => `t${place}`);
  for (const kept of ['a', {trackIds: []}, ['a', 'a'], ['a', ''], ['a', 7], ['x'.repeat(257)], tooMany]) {
    assert.throws(() => handBuiltPlaylistOf(kept), new HandBuiltPlaylistError('The playlist kept in this browser could not be read'));
  }
});
