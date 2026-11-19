// Issue #146: what the track list shows for a search.
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {trackListViewModel} from '../../../../../music_explorer/frameworks/explorer/assets/app/adapters/presenters/track-list-presenter.js';
import {emptyTrackResults} from '../../../../../music_explorer/frameworks/explorer/assets/app/domain/track-search.js';

const tracks = [{handle: 'a', title: 'Alpha', artist: 'Ann'}, {handle: 'b', display_label: 'Beta'}, {handle: 'c'}];
const view = changes => trackListViewModel({tracks, results: emptyTrackResults('q'), searchState: 'ready', failure: null,
  currentTrackId: 'b', ...changes});

test('rows show each track title and artist, marking the current track', () => {
  assert.deepEqual(view().rows, [
    {trackId: 'a', title: 'Alpha', artist: 'Ann', current: false},
    {trackId: 'b', title: 'Beta', artist: 'Unknown artist', current: true},
    {trackId: 'c', title: 'c', artist: 'Unknown artist', current: false}]);
});

test('the caption and status count the tracks, against the library total when known', () => {
  assert.deepEqual([view().caption, view().status], ['3 tracks', '3 tracks loaded']);
  const counted = view({results: {...emptyTrackResults('q'), metadata: {track_count: 40}}});
  assert.deepEqual([counted.caption, counted.status], ['Showing 3 of 40', 'Showing 3 of 40']);
});

test('the status says when a search is running or has failed', () => {
  assert.equal(view({searchState: 'debouncing'}).status, 'Searching tracks…');
  assert.equal(view({searchState: 'loading'}).status, 'Searching tracks…');
  const failed = view({searchState: 'failed', failure: {message: 'offline'}});
  assert.deepEqual([failed.status, failed.retry], ['Search failed: offline', true]);
  assert.equal(view().retry, false);
});

test('the empty message invites a search, or says nothing matched', () => {
  assert.deepEqual([view({tracks: [], searchState: 'idle'}).emptyMessage, view({tracks: [], searchState: 'idle'}).emptyHidden],
    ['Search for tracks to begin', false]);
  assert.deepEqual([view({tracks: []}).emptyMessage, view({tracks: []}).emptyHidden], ['No tracks match your search', false]);
  assert.equal(view({tracks: [], searchState: 'loading'}).emptyHidden, true);
  assert.equal(view().emptyHidden, true);
});

test('more results are offered while there is a next page, and not while one loads', () => {
  assert.equal(view().loadMore, null);
  const paged = {...emptyTrackResults('q'), nextCursor: 'c1'};
  assert.deepEqual(view({results: paged}).loadMore, {disabled: false});
  const loading = view({results: paged, searchState: 'loading'});
  assert.deepEqual([loading.busy, loading.loadMore], [true, {disabled: true}]);
});
