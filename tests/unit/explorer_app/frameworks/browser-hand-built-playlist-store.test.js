// Issue #278: the hand-built playlist is kept in this browser's local storage, as JSON under one key.
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {browserHandBuiltPlaylistStore, HAND_BUILT_PLAYLIST_KEY} from '../../../../music_explorer/frameworks/explorer/assets/app/frameworks/browser-hand-built-playlist-store.js';
import {HAND_BUILT_PLAYLIST_STORE} from '../../../../music_explorer/frameworks/explorer/assets/app/application/ports/hand-built-playlist-store.js';
import {requirePort} from '../../../../music_explorer/frameworks/explorer/assets/app/application/ports/port.js';

function memoryStorage(items = {}) {
  return {items, getItem: key => (Object.hasOwn(items, key) ? items[key] : null), setItem(key, value) { items[key] = String(value); }};
}

test('the store saves the track IDs as JSON and loads them back as they were saved', () => {
  const storage = memoryStorage();
  const store = requirePort(HAND_BUILT_PLAYLIST_STORE, browserHandBuiltPlaylistStore(storage));
  assert.equal(store.load(), null, 'nothing kept yet');
  store.save(['a', 'b']);
  assert.deepEqual([HAND_BUILT_PLAYLIST_KEY, storage.items[HAND_BUILT_PLAYLIST_KEY]], ['music-explorer.hand-built-playlist.v1', '["a","b"]']);
  assert.deepEqual(store.load(), ['a', 'b']);
});

test('what is kept is handed back unchecked, and a browser that refuses storage throws', () => {
  assert.deepEqual(browserHandBuiltPlaylistStore(memoryStorage({[HAND_BUILT_PLAYLIST_KEY]: '{"x":1}'})).load(), {x: 1});
  assert.equal(browserHandBuiltPlaylistStore(memoryStorage({[HAND_BUILT_PLAYLIST_KEY]: '{oops'})).load(), '{oops',
    'text that is not JSON comes back as text, for the playlist rules to refuse');
  const refusing = {getItem() { throw new Error('SecurityError'); }, setItem() { throw new Error('QuotaExceededError'); }};
  assert.throws(() => browserHandBuiltPlaylistStore(refusing).load(), /SecurityError/);
  assert.throws(() => browserHandBuiltPlaylistStore(refusing).save(['a']), /QuotaExceededError/);
  assert.throws(() => browserHandBuiltPlaylistStore(null).load(), /This browser offers no local storage/);
});
