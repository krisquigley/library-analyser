// Issue #146: what the track list shows for a search.
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {trackBpmBadges, trackListViewModel} from '../../../../../music_explorer/frameworks/explorer/assets/app/adapters/presenters/track-list-presenter.js';
import {emptyTrackResults} from '../../../../../music_explorer/frameworks/explorer/assets/app/domain/track-search.js';

const tracks = [{handle: 'a', title: 'Alpha', artist: 'Ann'}, {handle: 'b', display_label: 'Beta'}, {handle: 'c'}];
const view = changes => trackListViewModel({tracks, results: emptyTrackResults('q'), searchState: 'ready', failure: null,
  currentTrackId: 'b', trackBpms: new Map([['a', 123.6], ['c', null]]), ...changes});

test('rows show each track title and artist, a BPM badge when the graph knows it, and mark the current track (#235)', () => {
  assert.deepEqual(view().rows, [
    {trackId: 'a', title: 'Alpha', artist: 'Ann', bpmBadge: '124 BPM', current: false},
    {trackId: 'b', title: 'Beta', artist: 'Unknown artist', bpmBadge: null, current: true},
    {trackId: 'c', title: 'c', artist: 'Unknown artist', bpmBadge: null, current: false}]);
  assert.equal(view({trackBpms: undefined}).rows[0].bpmBadge, null, 'no graph yet, no badges');
});

test('the caption and status count the tracks, against the library total when known', () => {
  assert.deepEqual([view().caption, view().status], ['3 tracks', '3 tracks']);
  const counted = view({results: {...emptyTrackResults('q'), metadata: {track_count: 40}}});
  assert.deepEqual([counted.caption, counted.status], ['3 of 40 tracks', '3 of 40 tracks']);
  assert.equal(view({tracks: [], searchState: 'idle'}).status, '', 'nothing to count before a search');
});

test('each state has its own tone: waiting, searching, results, nothing found, or failed (#235)', () => {
  assert.equal(view({tracks: [], searchState: 'idle'}).tone, 'idle');
  assert.equal(view({searchState: 'debouncing'}).tone, 'searching');
  assert.equal(view().tone, 'results');
  assert.equal(view({tracks: []}).tone, 'empty');
  assert.equal(view({searchState: 'failed', failure: {message: 'offline'}}).tone, 'failed');
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

test('the BPM badges for rows already shown, once the graph knows them (#235)', () => {
  assert.deepEqual(trackBpmBadges(tracks, new Map([['a', 99.5]])),
    [{trackId: 'a', bpmBadge: '100 BPM'}, {trackId: 'b', bpmBadge: null}, {trackId: 'c', bpmBadge: null}]);
});
