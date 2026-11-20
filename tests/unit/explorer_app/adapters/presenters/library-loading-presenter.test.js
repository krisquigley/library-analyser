// Issue #146: the loading screen as each library refresh event leaves it.
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {presentLibraryRefreshEvent}
  from '../../../../../music_explorer/frameworks/explorer/assets/app/adapters/presenters/library-loading-presenter.js';

const working = {stage: 'refresh', hidden: false, errorText: '', errorShown: false, retryShown: false};

test('while a refresh works, the screen names its stage', () => {
  assert.deepEqual(presentLibraryRefreshEvent({type: 'library-refresh-started'}), {...working, statusText: 'Preparing library view'});
  assert.deepEqual(presentLibraryRefreshEvent({type: 'library-state-loading'}), {...working, statusText: 'Loading library state'});
});

test('a loaded or yielded refresh hides the screen', () => {
  const done = {stage: 'done', hidden: true, statusText: 'Library loaded', errorText: '', errorShown: false, retryShown: false};
  assert.deepEqual(presentLibraryRefreshEvent({type: 'library-loaded'}), done);
  assert.deepEqual(presentLibraryRefreshEvent({type: 'library-refresh-yielded'}), done);
});

test('a failed refresh shows its message and offers Retry', () => {
  assert.deepEqual(presentLibraryRefreshEvent({type: 'library-refresh-failed', message: 'network down'}),
    {stage: 'refresh', hidden: false, statusText: 'Unable to load library', errorText: 'network down', errorShown: true, retryShown: true});
});

test('an event the screen does not show leaves it alone', () => {
  assert.equal(presentLibraryRefreshEvent({type: 'something-else'}), null);
});
