// Issue #146: the library loading screen, drawn from its view model.
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {installFakeDocument} from '../fake-document.js';
import {libraryLoadingView} from '../../../../../music_explorer/frameworks/explorer/assets/app/frameworks/views/library-loading-view.js';

const IDS = ['loading-surface', 'loading-status', 'loading-error', 'loading-retry'];
const screen = (fields = {}) => ({stage: 'refresh', hidden: false, statusText: 'Preparing library view', errorText: '',
  errorShown: false, retryShown: false, ...fields});

test('a working refresh shows its stage on a visible, unbusy surface, keeping the surface class', () => {
  const roots = installFakeDocument(IDS);
  roots['loading-surface'].className = 'loading-surface done';
  libraryLoadingView({onRetry() {}}).show(screen());
  assert.equal(roots['loading-surface'].className, 'loading-surface refresh');
  assert.equal(roots['loading-surface'].hidden, false);
  assert.equal(roots['loading-surface'].getAttribute('aria-busy'), 'false');
  assert.equal(roots['loading-status'].textContent, 'Preparing library view');
  assert.equal(roots['loading-status'].getAttribute('role'), 'status');
  assert.equal(roots['loading-error'].hidden, true);
  assert.equal(roots['loading-retry'].hidden, true);
});

test('a failure shows its message as an alert and offers Retry', () => {
  const roots = installFakeDocument(IDS);
  let retried = 0;
  const view = libraryLoadingView({onRetry: () => { retried += 1; }});
  view.mount();
  view.show(screen({statusText: 'Unable to load library', errorText: 'network down', errorShown: true, retryShown: true}));
  assert.equal(roots['loading-error'].textContent, 'network down');
  assert.equal(roots['loading-error'].getAttribute('role'), 'alert');
  assert.equal(roots['loading-error'].hidden, false);
  assert.equal(roots['loading-retry'].hidden, false);
  roots['loading-retry'].onclick();
  assert.equal(retried, 1);
});

test('a loaded library hides the surface', () => {
  const roots = installFakeDocument(IDS);
  libraryLoadingView({onRetry() {}}).show(screen({stage: 'done', hidden: true, statusText: 'Library loaded'}));
  assert.ok(roots['loading-surface'].classList.contains('done'));
  assert.equal(roots['loading-surface'].hidden, true);
  assert.equal(roots['loading-status'].textContent, 'Library loaded');
});

test('without its elements the view does nothing', () => {
  installFakeDocument([]);
  const view = libraryLoadingView({onRetry() {}});
  view.mount();
  view.show(screen());
});
