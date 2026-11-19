// Issue #146: a use case refuses an adapter that does not implement its port.
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {requirePort} from '../../../../../music_explorer/frameworks/explorer/assets/app/application/ports/port.js';
import {EXPLORER_API, MOOD_GRAPHS, PLAYLIST_DOWNLOADS} from '../../../../../music_explorer/frameworks/explorer/assets/app/application/ports/explorer-api.js';
import {EVENT_BUS} from '../../../../../music_explorer/frameworks/explorer/assets/app/application/ports/event-bus.js';
import {PLAYLIST_FILE} from '../../../../../music_explorer/frameworks/explorer/assets/app/application/ports/playlist-file.js';
import {GRAPH_SESSION} from '../../../../../music_explorer/frameworks/explorer/assets/app/application/ports/graph-session.js';
import {CLOCK} from '../../../../../music_explorer/frameworks/explorer/assets/app/application/ports/clock.js';

test('the ports name the operations their adapters provide', () => {
  assert.deepEqual(EXPLORER_API.operations, ['downloadPlaylist', 'loadMoodGraph']);
  assert.deepEqual([PLAYLIST_DOWNLOADS.name, PLAYLIST_DOWNLOADS.operations], ['ExplorerApi', ['downloadPlaylist']]);
  assert.deepEqual([MOOD_GRAPHS.name, MOOD_GRAPHS.operations], ['ExplorerApi', ['loadMoodGraph']]);
  assert.deepEqual(GRAPH_SESSION.operations, ['read', 'write']);
  assert.deepEqual(CLOCK.operations, ['nextFrame']);
  assert.deepEqual(EVENT_BUS.operations, ['publish', 'subscribe']);
  assert.deepEqual(PLAYLIST_FILE.operations, ['save']);
});

test('an adapter with every operation is accepted as it is', () => {
  const adapter = {save() {}};
  assert.equal(requirePort(PLAYLIST_FILE, adapter), adapter);
});

test('an adapter missing an operation is refused', () => {
  assert.throws(() => requirePort(EVENT_BUS, {publish() {}}), /EventBus needs subscribe/);
  assert.throws(() => requirePort(EXPLORER_API, undefined), /ExplorerApi needs downloadPlaylist/);
});
