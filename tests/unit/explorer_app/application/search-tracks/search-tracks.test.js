// Issue #146: searching the library's tracks a page at a time.
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {createTrackSearch} from '../../../../../music_explorer/frameworks/explorer/assets/app/application/search-tracks/search-tracks.js';
import {TRACK_SEARCH_EVENT_TYPES} from '../../../../../music_explorer/frameworks/explorer/assets/app/application/search-tracks/track-search-events.js';
import {emptyTrackResults} from '../../../../../music_explorer/frameworks/explorer/assets/app/domain/track-search.js';

function memorySession() {
  let session = {searchState: 'idle', results: emptyTrackResults(), failure: null};
  return {read: () => session, write: changes => { session = {...session, ...changes}; }};
}

const page = (handles, nextCursor = null) => ({tracks: handles.map(handle => ({handle})), metadata: {track_count: 3}, nextCursor});

function harness({searchTracks, wait = async () => {}} = {}) {
  const requests = [];
  const published = [];
  const session = memorySession();
  const trackSearch = createTrackSearch({
    explorerApi: {searchTracks: searchTracks || (async request => { requests.push(request); return page(['one', 'two'], 'c1'); })},
    trackSession: session, clock: {wait}, eventBus: {publish: event => published.push(event), subscribe() {}},
  });
  return {trackSearch, session, requests, published, types: () => published.map(event => event.type)};
}

test('the event types are the ones the use case publishes', () => {
  assert.deepEqual(TRACK_SEARCH_EVENT_TYPES, ['track-search-edited', 'track-search-started', 'track-page-loaded', 'track-search-failed']);
});

test('a typed query waits 150 ms, then loads its first page', async () => {
  const waits = [];
  const {trackSearch, session, requests, types} = harness({wait: async ms => { waits.push(ms); }});
  await trackSearch.queryTyped('  alpha ');
  assert.deepEqual(waits, [150]);
  assert.deepEqual(requests, [{query: 'alpha', cursor: null}]);
  assert.deepEqual(types(), ['track-search-edited', 'track-search-started', 'track-page-loaded']);
  assert.equal(session.read().searchState, 'ready');
  assert.deepEqual(session.read().results.tracks.map(t => t.handle), ['one', 'two']);
});

test('an event carries the search as it then stands', async () => {
  const {trackSearch, published} = harness();
  await trackSearch.queryTyped('alpha');
  assert.deepEqual(published.map(event => event.searchState), ['debouncing', 'loading', 'ready']);
  assert.deepEqual(published[0].results, emptyTrackResults('alpha'));
});

test('clearing the query empties the results without a request', async () => {
  const {trackSearch, session, requests, types} = harness();
  await trackSearch.queryTyped('   ');
  assert.deepEqual(requests, []);
  assert.deepEqual(types(), ['track-search-edited']);
  assert.equal(session.read().searchState, 'idle');
});

test('typing again before the wait ends drops the earlier query', async () => {
  const waits = [];
  const {trackSearch, requests} = harness({wait: () => new Promise(resolve => waits.push(resolve))});
  const first = trackSearch.queryTyped('al');
  const second = trackSearch.queryTyped('alpha');
  waits[0]();
  waits[1]();
  await Promise.all([first, second]);
  assert.deepEqual(requests, [{query: 'alpha', cursor: null}]);
});

test('more results are appended from the next cursor, and nothing more is asked once they run out', async () => {
  const answers = [page(['one'], 'c1'), page(['two'])];
  const requests = [];
  const {trackSearch, session} = harness({searchTracks: async request => { requests.push(request); return answers.shift(); }});
  await trackSearch.loadPage({query: 'alpha'});
  await trackSearch.loadMore();
  await trackSearch.loadMore();
  assert.deepEqual(requests, [{query: 'alpha', cursor: null}, {query: 'alpha', cursor: 'c1'}]);
  assert.deepEqual(session.read().results.tracks.map(t => t.handle), ['one', 'two']);
});

test('a page is not asked for while another is loading, or for a blank query', async () => {
  let answer;
  const requests = [];
  const {trackSearch} = harness({searchTracks: request => { requests.push(request); return new Promise(resolve => { answer = resolve; }); }});
  const loading = trackSearch.loadPage({query: 'alpha'});
  await trackSearch.loadPage({query: 'beta'});
  await trackSearch.loadPage({query: ' '});
  answer(page(['one']));
  await loading;
  assert.deepEqual(requests, [{query: 'alpha', cursor: null}]);
});

test('a failed page says why and can be retried as it was asked', async () => {
  const answers = [Promise.reject(new Error('search temporarily unavailable')), Promise.resolve(page(['one']))];
  const requests = [];
  const {trackSearch, session, published} = harness({searchTracks: request => { requests.push(request); return answers.shift(); }});
  await trackSearch.loadPage({query: 'alpha', cursor: 'c9', append: true});
  assert.equal(session.read().searchState, 'failed');
  assert.deepEqual(session.read().failure, {message: 'search temporarily unavailable', query: 'alpha', cursor: 'c9', append: true});
  assert.equal(published.at(-1).type, 'track-search-failed');
  await trackSearch.retry();
  assert.deepEqual(requests, [{query: 'alpha', cursor: 'c9'}, {query: 'alpha', cursor: 'c9'}]);
  assert.deepEqual([session.read().searchState, session.read().failure], ['ready', null]);
});

test('an answer for a superseded search is dropped', async () => {
  let answer;
  const {trackSearch, session} = harness({searchTracks: () => new Promise(resolve => { answer = resolve; })});
  const loading = trackSearch.loadPage({query: 'alpha'});
  await trackSearch.queryTyped('');
  answer(page(['late']));
  await loading;
  assert.deepEqual([session.read().searchState, session.read().results.tracks], ['idle', []]);
});
