// Issue #146: a use case refuses an adapter that does not implement its port.
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {requirePort} from '../../../../../music_explorer/frameworks/explorer/assets/app/application/ports/port.js';
import {EXPLORER_API, HAND_BUILT_PLAYLIST_DOWNLOADS, HAND_BUILT_PLAYLIST_PREVIEWS, MOOD_GRAPHS, PLAYLIST_DOWNLOADS, PLAYLIST_PREVIEWS, SELECTIONS, TRACK_SEARCHES, TAG_WRITES, TRACK_LABELS} from '../../../../../music_explorer/frameworks/explorer/assets/app/application/ports/explorer-api.js';
import {EVENT_BUS} from '../../../../../music_explorer/frameworks/explorer/assets/app/application/ports/event-bus.js';
import {PLAYLIST_DRAFT_SESSION} from '../../../../../music_explorer/frameworks/explorer/assets/app/application/ports/playlist-draft-session.js';
import {PLAYLIST_FILE} from '../../../../../music_explorer/frameworks/explorer/assets/app/application/ports/playlist-file.js';
import {GRAPH_SESSION} from '../../../../../music_explorer/frameworks/explorer/assets/app/application/ports/graph-session.js';
import {TRACK_SEARCH_SESSION} from '../../../../../music_explorer/frameworks/explorer/assets/app/application/ports/track-search-session.js';
import {CLOCK, DELAYS, FRAMES} from '../../../../../music_explorer/frameworks/explorer/assets/app/application/ports/clock.js';
import {GRAPH_RENDERER} from '../../../../../music_explorer/frameworks/explorer/assets/app/application/ports/graph-renderer.js';
import {HAND_BUILT_PLAYLIST_STORE} from '../../../../../music_explorer/frameworks/explorer/assets/app/application/ports/hand-built-playlist-store.js';

test('the ports name the operations their adapters provide', () => {
  assert.deepEqual(EXPLORER_API.operations, ['downloadPlaylist', 'previewPlaylist', 'listSavedPlaylistRecipes', 'loadSavedPlaylistRecipe', 'previewTagWrite', 'applyTagWrite', 'labelTracks', 'downloadHandBuiltPlaylist', 'previewHandBuiltPlaylist', 'loadMoodGraph', 'searchTracks', 'chooseCurrentTrack', 'applyHistory',
    'loadTrackDetail', 'loadLibraryState']);
  assert.deepEqual([TRACK_LABELS.name, TRACK_LABELS.operations], ['ExplorerApi', ['labelTracks']]);
  assert.deepEqual([HAND_BUILT_PLAYLIST_DOWNLOADS.name, HAND_BUILT_PLAYLIST_DOWNLOADS.operations], ['ExplorerApi', ['downloadHandBuiltPlaylist']]);
  assert.deepEqual([HAND_BUILT_PLAYLIST_PREVIEWS.name, HAND_BUILT_PLAYLIST_PREVIEWS.operations], ['ExplorerApi', ['previewHandBuiltPlaylist']]);
  assert.deepEqual([HAND_BUILT_PLAYLIST_STORE.name, HAND_BUILT_PLAYLIST_STORE.operations], ['HandBuiltPlaylistStore', ['load', 'save']]);
  assert.deepEqual(SELECTIONS.operations, ['chooseCurrentTrack', 'applyHistory', 'loadTrackDetail', 'loadLibraryState']);
  assert.deepEqual([TRACK_SEARCHES.name, TRACK_SEARCHES.operations], ['ExplorerApi', ['searchTracks']]);
  assert.deepEqual([PLAYLIST_DOWNLOADS.name, PLAYLIST_DOWNLOADS.operations], ['ExplorerApi', ['downloadPlaylist']]);
  assert.deepEqual([MOOD_GRAPHS.name, MOOD_GRAPHS.operations], ['ExplorerApi', ['loadMoodGraph']]);
  assert.deepEqual([PLAYLIST_PREVIEWS.name, PLAYLIST_PREVIEWS.operations], ['ExplorerApi', ['previewPlaylist']]);
  assert.deepEqual([TAG_WRITES.name, TAG_WRITES.operations], ['ExplorerApi', ['previewTagWrite', 'applyTagWrite']]);
  assert.deepEqual([PLAYLIST_DRAFT_SESSION.name, PLAYLIST_DRAFT_SESSION.operations], ['PlaylistDraftSession', ['read', 'write']]);
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
