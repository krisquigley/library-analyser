// Issue #146: refreshing the library view is a transitions table, not scattered status checks.
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {LIBRARY_REFRESH_STATES, LibraryRefreshTransitionError, nextLibraryRefreshState}
  from '../../../../music_explorer/frameworks/explorer/assets/app/domain/library-refresh.js';

test('a refresh prepares, reads the library state, then is loaded', () => {
  assert.deepEqual(LIBRARY_REFRESH_STATES, ['idle', 'preparing', 'reading', 'loaded', 'failed']);
  assert.equal(nextLibraryRefreshState('idle', 'begin'), 'preparing');
  assert.equal(nextLibraryRefreshState('preparing', 'read'), 'reading');
  assert.equal(nextLibraryRefreshState('reading', 'finish'), 'loaded');
});

test('a newer refresh may begin from any state', () => {
  for (const state of LIBRARY_REFRESH_STATES) assert.equal(nextLibraryRefreshState(state, 'begin'), 'preparing');
});

test('a refresh in flight may fail, or yield to a newer selection, which ends its loading', () => {
  for (const state of ['preparing', 'reading']) {
    assert.equal(nextLibraryRefreshState(state, 'fail'), 'failed');
    assert.equal(nextLibraryRefreshState(state, 'yield'), 'loaded');
  }
});

test('an illegal transition is a domain error', () => {
  assert.throws(() => nextLibraryRefreshState('idle', 'finish'), LibraryRefreshTransitionError);
  assert.throws(() => nextLibraryRefreshState('preparing', 'finish'), /cannot finish while preparing/);
  assert.throws(() => nextLibraryRefreshState('loaded', 'fail'), LibraryRefreshTransitionError);
  assert.throws(() => nextLibraryRefreshState('unknown', 'begin'), LibraryRefreshTransitionError);
});
