// Issue #138: previewing the drafted playlist, walked by the same rule as the M3U download.
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {createPlaylistPreview} from '../../../../../music_explorer/frameworks/explorer/assets/app/application/preview-playlist/preview-playlist.js';
import {PLAYLIST_PREVIEW_EVENT_TYPES} from '../../../../../music_explorer/frameworks/explorer/assets/app/application/preview-playlist/playlist-preview-events.js';
import {EMPTY_PLAYLIST_DRAFT} from '../../../../../music_explorer/frameworks/explorer/assets/app/domain/playlist-draft.js';

const PREVIEW = Object.freeze({tracks: [], transitions: [], complete: true, warning: null});

function harness({previewPlaylist} = {}) {
  const requests = [];
  const published = [];
  const draft = {...EMPTY_PLAYLIST_DRAFT, bpmMin: '120', bpmMax: '128'};
  const explorerApi = {previewPlaylist: previewPlaylist || (async recipe => { requests.push(recipe); return PREVIEW; })};
  const playlistPreview = createPlaylistPreview({explorerApi, playlistDraft: {read: () => ({draft}), write() {}},
    eventBus: {publish: event => published.push(event), subscribe() {}}});
  return {playlistPreview, requests, published};
}

test('the event types are the ones the use case publishes', () => {
  assert.deepEqual(PLAYLIST_PREVIEW_EVENT_TYPES, ['playlist-preview-started', 'playlist-previewed', 'playlist-preview-failed']);
});

test('a preview asks for the drafted recipe from the start track and publishes what came back', async () => {
  const {playlistPreview, requests, published} = harness();
  await playlistPreview.preview('track-1');
  assert.deepEqual(requests.map(recipe => [recipe.startTrackId, recipe.bpmMin, recipe.bpmMax]), [['track-1', '120', '128']]);
  assert.deepEqual(published, [{type: 'playlist-preview-started'}, {type: 'playlist-previewed', preview: PREVIEW}]);
  assert.equal(playlistPreview.previewState(), 'previewed');
});

test('a refused preview publishes the reason', async () => {
  const {playlistPreview, published} = harness({previewPlaylist: async () => { throw new Error('bpm bounds must be ordered'); }});
  await playlistPreview.preview('track-1');
  assert.deepEqual(published.at(-1), {type: 'playlist-preview-failed', message: 'bpm bounds must be ordered'});
  assert.equal(playlistPreview.previewState(), 'failed');
});

test('without a start track the preview fails without asking the server', async () => {
  const {playlistPreview, requests, published} = harness();
  await playlistPreview.preview(null);
  assert.deepEqual(requests, []);
  assert.deepEqual(published.at(-1), {type: 'playlist-preview-failed', message: 'Select a start track first'});
});

test('an overtaken preview is never shown', async () => {
  const answers = [];
  const {playlistPreview, published} = harness({previewPlaylist: () => new Promise(resolve => answers.push(resolve))});
  const first = playlistPreview.preview('track-1');
  const second = playlistPreview.preview('track-2');
  const later = {...PREVIEW, warning: 'later'};
  answers[1](later);
  await second;
  answers[0]({...PREVIEW, warning: 'stale'});
  await first;
  assert.deepEqual(published.map(event => event.type),
    ['playlist-preview-started', 'playlist-preview-started', 'playlist-previewed']);
  assert.equal(published.at(-1).preview, later);
});
