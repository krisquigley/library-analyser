// Issue #146: a use case refuses an adapter that does not implement its port.
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {requirePort} from '../../../../../music_explorer/frameworks/explorer/assets/app/application/ports/port.js';
import {EXPLORER_API, MOOD_GRAPHS, PLAYLIST_DOWNLOADS, SELECTIONS, TRACK_SEARCHES} from '../../../../../music_explorer/frameworks/explorer/assets/app/application/ports/explorer-api.js';
import {EVENT_BUS} from '../../../../../music_explorer/frameworks/explorer/assets/app/application/ports/event-bus.js';
import {PLAYLIST_FILE} from '../../../../../music_explorer/frameworks/explorer/assets/app/application/ports/playlist-file.js';
import {GRAPH_SESSION} from '../../../../../music_explorer/frameworks/explorer/assets/app/application/ports/graph-session.js';
import {TRACK_SEARCH_SESSION} from '../../../../../music_explorer/frameworks/explorer/assets/app/application/ports/track-search-session.js';
import {CLOCK, DELAYS, FRAMES} from '../../../../../music_explorer/frameworks/explorer/assets/app/application/ports/clock.js';
import {GRAPH_RENDERER} from '../../../../../music_explorer/frameworks/explorer/assets/app/application/ports/graph-renderer.js';

test('the ports name the operations their adapters provide', () => {
  assert.deepEqual(EXPLORER_API.operations, ['downloadPlaylist', 'loadMoodGraph', 'searchTracks', 'chooseCurrentTrack', 'applyHistory',
    'loadTrackDetail', 'loadLibraryState']);
  assert.deepEqual(SELECTIONS.operations, ['chooseCurrentTrack', 'applyHistory', 'loadTrackDetail', 'loadLibraryState']);
  assert.deepEqual([TRACK_SEARCHES.name, TRACK_SEARCHES.operations], ['ExplorerApi', ['searchTracks']]);
  assert.deepEqual([PLAYLIST_DOWNLOADS.name, PLAYLIST_DOWNLOADS.operations], ['ExplorerApi', ['downloadPlaylist']]);
  assert.deepEqual([MOOD_GRAPHS.name, MOOD_GRAPHS.operations], ['ExplorerApi', ['loadMoodGraph']]);
  assert.deepEqual(GRAPH_SESSION.operations, ['read', 'write']);
  assert.deepEqual(CLOCK.operations, ['nextFrame', 'wait']);
  assert.deepEqual([FRAMES.name, FRAMES.operations], ['Clock', ['nextFrame']]);
  assert.deepEqual([DELAYS.name, DELAYS.operations], ['Clock', ['wait']]);
  assert.deepEqual(TRACK_SEARCH_SESSION.operations, ['read', 'write']);
  assert.deepEqual(EVENT_BUS.operations, ['publish', 'subscribe']);
  assert.deepEqual(PLAYLIST_FILE.operations, ['save']);
  assert.deepEqual(GRAPH_RENDERER.operations, ['pause', 'resume', 'canPause']);
});

test('an adapter with every operation is accepted as it is', () => {
  const adapter = {save() {}};
  assert.equal(requirePort(PLAYLIST_FILE, adapter), adapter);
});

test('an adapter missing an operation is refused', () => {
  assert.throws(() => requirePort(EVENT_BUS, {publish() {}}), /EventBus needs subscribe/);
  assert.throws(() => requirePort(EXPLORER_API, undefined), /ExplorerApi needs downloadPlaylist/);
});
