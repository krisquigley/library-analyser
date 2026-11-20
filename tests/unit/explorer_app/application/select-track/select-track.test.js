// Issue #146: choosing the current track, undo and reset, and loading its detail, with the races they meet.
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {createTrackSelection} from '../../../../../music_explorer/frameworks/explorer/assets/app/application/select-track/select-track.js';
import {TRACK_SELECTION_EVENT_TYPES} from '../../../../../music_explorer/frameworks/explorer/assets/app/application/select-track/track-selection-events.js';

function deferred() {
  let resolve, reject;
  const promise = new Promise((ok, fail) => { resolve = ok; reject = fail; });
  return {promise, resolve, reject};
}
const flush = async () => { for (let i = 0; i < 10; i++) await Promise.resolve(); };
const snapshot = (id, epoch = 1) => ({current_track_id: id, selection_epoch: epoch, history: []});

function harness({current = null, epoch = 0} = {}) {
  const calls = [];
  const answers = [];
  const answer = name => (...args) => { const pending = deferred(); calls.push({name, args}); answers.push(pending); return pending.promise; };
  const explorerApi = {chooseCurrentTrack: answer('choose'), applyHistory: answer('history'),
    loadTrackDetail: answer('detail'), loadLibraryState: answer('state')};
  let record = {snapshot: snapshot(current, epoch), epoch, selectionState: current ? 'shown' : 'none'};
  const session = {read: () => record, write: changes => { record = {...record, ...changes}; }};
  let ticket = 0;
  const tickets = {nextTicket: () => ++ticket, clientId: () => 'tab-test'};
  const published = [];
  const eventBus = {publish: event => published.push(event), subscribe() {}};
  const selection = createTrackSelection({explorerApi, selectionTickets: tickets, selectionSession: session, eventBus});
  const last = name => answers[calls.map(call => call.name).lastIndexOf(name)];
  return {selection, calls, last, published, types: () => published.map(event => event.type), record: () => record};
}

test('the event types are the ones the use case publishes', () => {
  assert.deepEqual(TRACK_SELECTION_EVENT_TYPES, ['track-chosen', 'selection-rewinding', 'selection-accepted',
    'selection-refused', 'library-selection-changed', 'no-track-selected', 'track-detail-loading', 'track-detail-loaded',
    'track-detail-failed']);
});

test('choosing shows the track at once, posts it with a ticket, then loads the detail the server accepted', async () => {
  const {selection, calls, last, published, types, record} = harness({epoch: 3});
  const chosen = selection.choose('A', {focusCamera: false});
  assert.equal(record().snapshot.current_track_id, 'A');
  assert.equal(record().selectionState, 'choosing');
  assert.deepEqual(calls[0], {name: 'choose', args: [{trackId: 'A', selectionToken: 1, selectionEpoch: 3, clientId: 'tab-test'}]});
  last('choose').resolve(snapshot('A', 4));
  await flush();
  assert.equal(record().epoch, 4);
  assert.deepEqual(calls[1], {name: 'detail', args: ['A']});
  last('detail').resolve({handle: 'A'});
  await chosen;
  assert.deepEqual(types(), ['track-chosen', 'selection-accepted', 'track-detail-loading', 'track-detail-loaded']);
  assert.deepEqual(published[1], {type: 'selection-accepted', trackId: 'A', focusCamera: false, rewound: false});
  assert.deepEqual(published[3], {type: 'track-detail-loaded', trackId: 'A', detail: {handle: 'A'}});
  assert.equal(record().selectionState, 'shown');
});

test('a track id is required to choose', async () => {
  const {selection} = harness();
  for (const id of ['', null, 3]) await assert.rejects(selection.choose(id), /A track id is required/);
});

test('a later choice makes the earlier answer stale: it neither selects nor loads', async () => {
  const {selection, calls, last, types, record} = harness();
  const first = selection.choose('A');
  const firstPost = last('choose');
  const second = selection.choose('B');
  firstPost.resolve(snapshot('A'));
  await first;
  assert.equal(record().snapshot.current_track_id, 'B');
  assert.deepEqual(calls.map(call => call.name), ['choose', 'choose']);
  last('choose').resolve(snapshot('B'));
  await flush();
  last('detail').resolve({handle: 'B'});
  await second;
  assert.deepEqual(types(), ['track-chosen', 'track-chosen', 'selection-accepted', 'track-detail-loading', 'track-detail-loaded']);
});

test('a refused choice says why and loads nothing', async () => {
  const {selection, calls, last, published, record} = harness();
  const chosen = selection.choose('A');
  last('choose').reject(new Error('Unknown track'));
  await chosen;
  assert.equal(record().selectionState, 'refused');
  assert.deepEqual(published.at(-1), {type: 'selection-refused', failure: {message: 'Unknown track'}});
  assert.equal(calls.length, 1);
});

test('undo or reset replaces a choice in flight, and reports whether the page should refresh', async () => {
  const {selection, last, types, record} = harness();
  const chosen = selection.choose('A');
  const choicePost = last('choose');
  const rewound = selection.rewind('reset');
  assert.equal(record().selectionState, 'rewinding');
  choicePost.resolve(snapshot('A'));
  await chosen;
  last('history').resolve(snapshot(null, 9));
  assert.equal(await rewound, true);
  assert.equal(record().snapshot.current_track_id, null);
  assert.equal(record().epoch, 9);
  assert.equal(record().selectionState, 'none');
  assert.deepEqual(types(), ['track-chosen', 'selection-rewinding', 'selection-accepted']);
});

test('a stale or refused undo does not ask for a refresh', async () => {
  const stale = harness();
  const undo = stale.selection.rewind('undo');
  const undoPost = stale.last('history');
  stale.selection.choose('B');
  undoPost.resolve(snapshot('PRIOR'));
  assert.equal(await undo, false);
  assert.equal(stale.record().snapshot.current_track_id, 'B');

  const refused = harness();
  const refusedUndo = refused.selection.rewind('undo');
  refused.last('history').reject(new Error('Nothing to undo'));
  assert.equal(await refusedUndo, false);
  assert.deepEqual(refused.published.at(-1), {type: 'selection-refused', failure: {message: 'Nothing to undo'}});
});

test('loading the detail of no track says there is none', async () => {
  const {selection, types, calls, record} = harness();
  await selection.loadDetail(selection.generation());
  assert.deepEqual(types(), ['no-track-selected']);
  assert.equal(calls.length, 0);
  assert.equal(record().selectionState, 'none');
});

test('overlapping loads of the same detail share one request', async () => {
  const {selection, calls, last} = harness({current: 'A'});
  const generation = selection.generation();
  const first = selection.loadDetail(generation);
  const second = selection.loadDetail(generation);
  last('detail').resolve({handle: 'A'});
  await Promise.all([first, second]);
  assert.deepEqual(calls.map(call => call.name), ['detail']);
});

test('a detail load for an older generation, or while the server decides, does nothing', async () => {
  const {selection, calls} = harness({current: 'A'});
  const old = selection.generation();
  selection.choose('B');
  await selection.loadDetail(old);
  await selection.loadDetail(selection.generation());
  assert.deepEqual(calls.map(call => call.name), ['choose']);
});

test('a failed detail can be retried until something newer happens', async () => {
  const {selection, calls, last, published, record} = harness({current: 'A'});
  await (async () => { const loading = selection.loadDetail(selection.generation()); last('detail').reject(new Error('Gone')); await loading; })();
  assert.equal(record().selectionState, 'detail-failed');
  assert.deepEqual(published.at(-1), {type: 'track-detail-failed', trackId: 'A', failure: {message: 'Gone'}});
  const retry = selection.retryDetail();
  last('detail').resolve({handle: 'A'});
  await retry;
  assert.equal(record().selectionState, 'shown');
  selection.choose('B');
  await selection.retryDetail();
  assert.equal(calls.filter(call => call.name === 'detail').length, 2);
});

test('a stale detail answer is dropped', async () => {
  const {selection, last, types} = harness({current: 'A'});
  const loading = selection.loadDetail(selection.generation());
  const detail = last('detail');
  selection.choose('B');
  detail.resolve({handle: 'A'});
  await loading;
  assert.deepEqual(types(), ['track-detail-loading', 'track-chosen']);
});

test('the library state settles the selection unless the server is still deciding', () => {
  const {selection, published, record} = harness({current: 'A', epoch: 1});
  selection.reconcile(snapshot('A', 2));
  assert.deepEqual([record().epoch, published.length], [2, 0]);
  selection.reconcile(snapshot('Z', 3));
  assert.deepEqual(published, [{type: 'library-selection-changed', trackId: 'Z'}]);
  assert.equal(record().snapshot.current_track_id, 'Z');
  selection.choose('B');
  selection.reconcile(snapshot('Q', 5));
  assert.equal(record().snapshot.current_track_id, 'B');
  assert.equal(selection.awaitingServer(), true);
});

test('a use case refuses adapters that do not implement its ports', () => {
  assert.throws(() => createTrackSelection({explorerApi: {}, selectionTickets: {}, selectionSession: {}, eventBus: {}}),
    /ExplorerApi needs chooseCurrentTrack/);
});

test('a choice the server rejects in favour of another track selects and loads that track instead', async () => {
  const {selection, calls, last, published, record} = harness();
  const chosen = selection.choose('A');
  last('choose').resolve({current_track_id: 'B', selection_epoch: 2, selection_accepted: false});
  await flush();
  assert.equal(record().snapshot.current_track_id, 'B');
  assert.deepEqual(calls.filter(call => call.name === 'detail').map(call => call.args), [['B']]);
  last('detail').resolve({handle: 'B'});
  await chosen;
  assert.deepEqual(published.find(event => event.type === 'selection-accepted').trackId, 'B');
});

test('after the library state confirms the same track, overlapping detail loads still share one request', async () => {
  const {selection, calls, last} = harness({current: 'A'});
  selection.reconcile(snapshot('A', 2));
  const generation = selection.generation();
  const loads = [selection.loadDetail(generation), selection.loadDetail(generation)];
  last('detail').resolve({handle: 'A'});
  await Promise.all(loads);
  assert.equal(calls.filter(call => call.name === 'detail').length, 1);
});

async function failedDetail() {
  const context = harness({current: 'A'});
  const loading = context.selection.loadDetail(context.selection.generation());
  context.last('detail').reject(new Error('Gone'));
  await loading;
  return context;
}

test('a retry answering after a newer choice changes nothing, whether it succeeds or fails', async () => {
  for (const settle of ['resolve', 'reject']) {
    const {selection, last, published, record} = await failedDetail();
    const retry = selection.retryDetail();
    const retried = last('detail');
    const chosen = selection.choose('B');
    last('choose').resolve(snapshot('B'));
    await flush();
    const before = published.length;
    retried[settle](settle === 'resolve' ? {handle: 'A'} : new Error('late'));
    await retry;
    assert.equal(published.length, before, settle);
    assert.equal(record().snapshot.current_track_id, 'B', settle);
    last('detail').resolve({handle: 'B'});
    await chosen;
  }
});

test('a refusal of an earlier choice says nothing once a later choice is in flight', async () => {
  const {selection, last, types, record} = harness();
  const first = selection.choose('A');
  const firstPost = last('choose');
  selection.choose('B');
  firstPost.reject(new Error('Unknown track'));
  await first;
  assert.ok(!types().includes('selection-refused'));
  assert.equal(record().snapshot.current_track_id, 'B');
  assert.equal(record().selectionState, 'choosing');
});

test('a stale detail failure is dropped too', async () => {
  const {selection, last, types} = harness({current: 'A'});
  const loading = selection.loadDetail(selection.generation());
  const detail = last('detail');
  selection.choose('B');
  detail.reject(new Error('Gone'));
  await loading;
  assert.ok(!types().includes('track-detail-failed'));
});

test('an undo makes a detail still loading stale', async () => {
  const {selection, last, types} = harness({current: 'A'});
  const loading = selection.loadDetail(selection.generation());
  const detail = last('detail');
  const undo = selection.rewind('undo');
  last('history').resolve(snapshot('PRIOR', 3));
  await undo;
  const before = types().length;
  detail.resolve({handle: 'A'});
  await loading;
  assert.equal(types().length, before);
});
