// Issue #146: refreshing the library view: wait for a paint, read the library state, reconcile the selection.
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {createLibraryRefresh}
  from '../../../../../music_explorer/frameworks/explorer/assets/app/application/refresh-library/refresh-library.js';
import {LIBRARY_REFRESH_EVENT_TYPES}
  from '../../../../../music_explorer/frameworks/explorer/assets/app/application/refresh-library/library-refresh-events.js';

function deferred() { let resolve, reject; const promise = new Promise((yes, no) => { resolve = yes; reject = no; }); return {promise, resolve, reject}; }
const flush = async () => { for (let i = 0; i < 10; i++) await Promise.resolve(); };

function harness({awaitingServer = false} = {}) {
  const frames = [], reads = [], published = [], calls = [];
  let generation = 1;
  const selection = {
    generation: () => generation, awaitingServer: () => awaitingServer,
    reconcile: snapshot => calls.push(['reconcile', snapshot]),
    loadDetail: async token => { calls.push(['loadDetail', token]); },
  };
  const libraryRefresh = createLibraryRefresh({
    explorerApi: {loadLibraryState: () => { const read = deferred(); reads.push(read); return read.promise; }},
    librarySelection: selection,
    clock: {nextFrame: () => { const frame = deferred(); frames.push(frame); return frame.promise; }},
    eventBus: {publish: event => published.push(event), subscribe() {}},
  });
  return {libraryRefresh, frames, reads, published, calls, types: () => published.map(event => event.type),
    chooseAnotherTrack: () => { generation += 1; }};
}

test('the event types are the ones the use case publishes', () => {
  assert.deepEqual(LIBRARY_REFRESH_EVENT_TYPES, ['library-refresh-started', 'library-state-loading', 'library-loaded',
    'library-refresh-yielded', 'library-refresh-failed']);
});

test('a refresh paints first, then reads the state, reconciles the selection and loads its detail', async () => {
  const h = harness();
  const done = h.libraryRefresh.refresh();
  assert.deepEqual(h.types(), ['library-refresh-started']);
  assert.equal(h.reads.length, 0, 'nothing is read before the loading screen can paint');
  h.frames[0].resolve(); await flush();
  assert.deepEqual(h.types(), ['library-refresh-started', 'library-state-loading']);
  h.reads[0].resolve({current_track_id: 'a'}); await done;
  assert.deepEqual(h.calls, [['reconcile', {current_track_id: 'a'}], ['loadDetail', 1]]);
  assert.deepEqual(h.types(), ['library-refresh-started', 'library-state-loading', 'library-loaded']);
  assert.deepEqual(h.published.map(event => event.refreshState), ['preparing', 'reading', 'loaded']);
  assert.equal(h.libraryRefresh.refreshState(), 'loaded');
});

test('a refresh begun while the selection waits for the server neither reconciles nor loads detail', async () => {
  const h = harness({awaitingServer: true});
  const done = h.libraryRefresh.refresh();
  h.frames[0].resolve(); await flush(); h.reads[0].resolve({current_track_id: 'old'}); await done;
  assert.deepEqual(h.calls, []);
  assert.equal(h.types().at(-1), 'library-loaded');
});

test('a stale refresh stops silently and never ends the newer one', async () => {
  const h = harness();
  const first = h.libraryRefresh.refresh();
  h.frames[0].resolve(); await flush();
  const second = h.libraryRefresh.refresh();
  h.reads[0].resolve({current_track_id: 'old'}); await first;
  assert.deepEqual(h.calls, [], 'the stale state is never reconciled');
  assert.equal(h.libraryRefresh.refreshState(), 'preparing');
  h.frames[1].resolve(); await flush(); h.reads[1].resolve({current_track_id: null}); await second;
  assert.equal(h.libraryRefresh.refreshState(), 'loaded');
});

test('a refresh yields when the listener chooses another track meanwhile', async () => {
  const h = harness();
  const done = h.libraryRefresh.refresh();
  h.frames[0].resolve(); await flush();
  h.chooseAnotherTrack();
  h.reads[0].resolve({current_track_id: 'old'}); await done;
  assert.deepEqual(h.calls, [], 'the older state never overwrites the newer choice');
  assert.equal(h.types().at(-1), 'library-refresh-yielded');
  assert.equal(h.libraryRefresh.refreshState(), 'loaded');
});

test('a failed read is announced with its message and rejects', async () => {
  const h = harness();
  const done = h.libraryRefresh.refresh();
  h.frames[0].resolve(); await flush();
  h.reads[0].reject(new Error('network down'));
  await assert.rejects(done, /network down/);
  assert.deepEqual(h.published.at(-1), {type: 'library-refresh-failed', refreshState: 'failed', message: 'network down'});
});

test('a failure without a message says loading failed', async () => {
  const h = harness();
  const done = h.libraryRefresh.refresh();
  h.frames[0].resolve(); await flush();
  h.reads[0].reject(null);
  await assert.rejects(done);
  assert.equal(h.published.at(-1).message, 'Loading failed');
});

test('a stale refresh that fails stays silent', async () => {
  const h = harness();
  const first = h.libraryRefresh.refresh();
  h.frames[0].resolve(); await flush();
  h.libraryRefresh.refresh();
  h.reads[0].reject(new Error('late failure'));
  await first;
  assert.ok(!h.types().includes('library-refresh-failed'));
});

test('the refresh needs every port it uses', () => {
  assert.throws(() => createLibraryRefresh({explorerApi: {}, librarySelection: {}, clock: {}, eventBus: {}}), /ExplorerApi needs loadLibraryState/);
});
