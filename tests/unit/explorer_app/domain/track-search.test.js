// Issue #146: searching the library's tracks, as a state machine over pages of results.
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {
  TRACK_SEARCH_STATES, TrackSearchTransitionError, emptyTrackResults, nextTrackSearchState, trackResultsWithPage,
} from '../../../../music_explorer/frameworks/explorer/assets/app/domain/track-search.js';

test('typing waits, then a page loads and is ready or fails', () => {
  assert.deepEqual(TRACK_SEARCH_STATES, ['idle', 'debouncing', 'loading', 'ready', 'failed']);
  assert.equal(nextTrackSearchState('idle', 'type'), 'debouncing');
  assert.equal(nextTrackSearchState('debouncing', 'fetch'), 'loading');
  assert.equal(nextTrackSearchState('loading', 'succeed'), 'ready');
  assert.equal(nextTrackSearchState('loading', 'fail'), 'failed');
});

test('typing or clearing the search is always allowed', () => {
  for (const state of TRACK_SEARCH_STATES) {
    assert.equal(nextTrackSearchState(state, 'type'), 'debouncing');
    assert.equal(nextTrackSearchState(state, 'clear'), 'idle');
  }
});

test('a page can be fetched from rest, for more results or a retry, but not while one loads', () => {
  for (const state of ['idle', 'debouncing', 'ready', 'failed']) assert.equal(nextTrackSearchState(state, 'fetch'), 'loading');
  const illegal = [['loading', 'fetch'], ['ready', 'succeed'], ['idle', 'fail'], ['unknown', 'type']];
  for (const [state, action] of illegal) {
    assert.throws(() => nextTrackSearchState(state, action),
      error => error instanceof TrackSearchTransitionError && error.message === `A track search cannot ${action} while ${state}`);
  }
});

test('results start empty for their query', () => {
  assert.deepEqual(emptyTrackResults('alpha'), {query: 'alpha', tracks: [], metadata: {}, nextCursor: null});
  assert.deepEqual(emptyTrackResults(), {query: '', tracks: [], metadata: {}, nextCursor: null});
});

test('a first page replaces the results and a further page is appended', () => {
  const first = trackResultsWithPage(emptyTrackResults('a'), {tracks: [{handle: 'one'}], metadata: {track_count: 2}, nextCursor: 'c1'});
  assert.deepEqual(first, {query: 'a', tracks: [{handle: 'one'}], metadata: {track_count: 2}, nextCursor: 'c1'});
  const more = trackResultsWithPage(first, {tracks: [{handle: 'two'}], metadata: {track_count: 2}, nextCursor: null}, {append: true});
  assert.deepEqual(more.tracks, [{handle: 'one'}, {handle: 'two'}]);
  assert.equal(more.nextCursor, null);
  assert.deepEqual(trackResultsWithPage(first, {tracks: [{handle: 'x'}], metadata: {}, nextCursor: null}).tracks, [{handle: 'x'}]);
});
