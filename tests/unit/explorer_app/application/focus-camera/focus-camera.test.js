// Issue #146: requesting, taking, animating and cancelling the camera's focus.
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {createCameraFocus} from '../../../../../music_explorer/frameworks/explorer/assets/app/application/focus-camera/focus-camera.js';
import {CAMERA_FOCUS_EVENT_TYPES} from '../../../../../music_explorer/frameworks/explorer/assets/app/application/focus-camera/camera-focus-events.js';

function harness(initial = {}) {
  let record = {pendingTrackId: null, frame: null, viewIntent: 0, selectionViewIntent: 0, focusGeneration: 0, ...initial};
  const session = {read: () => record, write: changes => { record = {...record, ...changes}; }};
  const published = [];
  const focus = createCameraFocus({focusSession: session, eventBus: {publish: event => published.push(event), subscribe() {}}});
  return {focus, published, record: () => record};
}

test('the event types are the ones the use case publishes', () => {
  assert.deepEqual(CAMERA_FOCUS_EVENT_TYPES, ['camera-view-claimed', 'camera-focus-cancelled', 'camera-focus-requested',
    'camera-focus-started', 'camera-focus-finished']);
});

test('requesting a focus cancels any arc in flight and waits for the track', () => {
  const {focus, published, record} = harness({frame: 7});
  focus.request('a');
  assert.deepEqual([record().pendingTrackId, record().frame], ['a', null]);
  assert.deepEqual(published, [{type: 'camera-focus-cancelled', frame: 7, cause: 'new-selection'},
    {type: 'camera-focus-requested', trackId: 'a'}]);
  focus.request(null);
  assert.equal(record().pendingTrackId, null);
});

test('cancelling stops the arc in flight but leaves a request waiting', () => {
  const {focus, published, record} = harness({pendingTrackId: 'a'});
  focus.cancel('graph-reframed');
  assert.deepEqual([record().pendingTrackId, record().focusGeneration, published], ['a', 1, []]);
});

test('the listener claiming the view ends any request and arc, and names the new view intent', () => {
  const {focus, published, record} = harness({pendingTrackId: 'a', frame: 3, viewIntent: 4});
  assert.equal(focus.claimView('listener-orbit'), 5);
  assert.deepEqual([record().pendingTrackId, record().frame], [null, null]);
  assert.deepEqual(published.map(event => event.type), ['camera-focus-cancelled', 'camera-view-claimed']);
  assert.equal(published[0].cause, 'listener-orbit');
  assert.equal(focus.viewIntent(), 5);
});

test('a waiting request is taken once, and only for the current track', () => {
  const {focus, record} = harness({pendingTrackId: 'a'});
  assert.equal(focus.peek(), 'a');
  assert.equal(focus.take('a'), 'a');
  assert.equal(record().pendingTrackId, null);
  assert.equal(focus.take('a'), null);
  const stale = harness({pendingTrackId: 'a'});
  assert.equal(stale.focus.take('b'), null);
  assert.equal(stale.record().pendingTrackId, null);
});

test('an arc runs while its generation is current, frame by frame, and says when it finishes', () => {
  const {focus, published, record} = harness();
  const arc = focus.begin();
  focus.frameScheduled(arc, 11);
  assert.equal(record().frame, 11);
  assert.equal(focus.frameRan(arc), true);
  assert.equal(record().frame, null);
  focus.frameScheduled(arc, 12);
  focus.frameRan(arc);
  focus.finished(arc);
  assert.deepEqual(published.at(-1), {type: 'camera-focus-finished'});
  const newer = focus.begin();
  assert.equal(focus.frameRan(arc), false);
  assert.notEqual(newer, arc);
});

test('beginning an arc cancels the one in flight and says which arc started', () => {
  const {focus, published} = harness({frame: 4, focusGeneration: 2});
  const arc = focus.begin();
  assert.equal(arc, 3);
  assert.deepEqual(published, [{type: 'camera-focus-cancelled', frame: 4, cause: 'new-focus'},
    {type: 'camera-focus-started', focusGeneration: 3}]);
});

test('an arc in flight is cancelled with its cause; an idle cancel or an unknown cause publishes nothing', () => {
  const {focus, published, record} = harness({frame: 9});
  assert.throws(() => focus.cancel('boredom'), /not cancelled for: boredom/);
  assert.deepEqual([record().frame, published], [9, []]);
  focus.cancel('camera-failure');
  focus.cancel('graph-filtered');
  assert.deepEqual(published, [{type: 'camera-focus-cancelled', frame: 9, cause: 'camera-failure'}]);
  assert.throws(() => focus.claimView(), /not cancelled for: undefined/);
});

test('a chosen track claims the view; once accepted it asks for focus while its claim still owns the view', () => {
  const {focus, published, record} = harness({viewIntent: 2});
  focus.claimViewForSelection('new-selection');
  assert.deepEqual([record().viewIntent, record().selectionViewIntent], [3, 3]);
  published.length = 0;
  assert.equal(focus.requestForAcceptedSelection('a'), true);
  assert.equal(focus.peek(), 'a');
  assert.deepEqual(published.map(event => event.type), ['camera-focus-requested']);
});

test('an accepted selection asks for nothing once the listener has claimed the view since', () => {
  const {focus, published} = harness();
  focus.claimViewForSelection('new-selection');
  focus.claimView('listener-orbit');
  published.length = 0;
  assert.equal(focus.requestForAcceptedSelection('a'), false);
  assert.deepEqual([focus.peek(), published], [null, []]);
});

test('an accepted selection that keeps the camera still clears any waiting focus', () => {
  const {focus} = harness({pendingTrackId: 'old'});
  focus.claimViewForSelection('new-selection');
  assert.equal(focus.requestForAcceptedSelection(null), true);
  assert.equal(focus.peek(), null);
});
