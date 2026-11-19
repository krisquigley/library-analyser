// Issue #146: requesting, taking, animating and cancelling the camera's focus.
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {createCameraFocus} from '../../../../../music_explorer/frameworks/explorer/assets/app/application/focus-camera/focus-camera.js';
import {CAMERA_FOCUS_EVENT_TYPES} from '../../../../../music_explorer/frameworks/explorer/assets/app/application/focus-camera/camera-focus-events.js';

function harness(initial = {}) {
  let record = {pendingTrackId: null, frame: null, viewIntent: 0, focusGeneration: 0, ...initial};
  const session = {read: () => record, write: changes => { record = {...record, ...changes}; }};
  const published = [];
  const focus = createCameraFocus({focusSession: session, eventBus: {publish: event => published.push(event), subscribe() {}}});
  return {focus, published, record: () => record};
}

test('the event types are the ones the use case publishes', () => {
  assert.deepEqual(CAMERA_FOCUS_EVENT_TYPES, ['camera-view-claimed', 'camera-focus-cancelled', 'camera-focus-requested',
    'camera-focus-finished']);
});

test('requesting a focus cancels any arc in flight and waits for the track', () => {
  const {focus, published, record} = harness({frame: 7});
  focus.request('a');
  assert.deepEqual([record().pendingTrackId, record().frame], ['a', null]);
  assert.deepEqual(published, [{type: 'camera-focus-cancelled', frame: 7}, {type: 'camera-focus-requested', trackId: 'a'}]);
  focus.request(null);
  assert.equal(record().pendingTrackId, null);
});

test('cancelling stops the arc in flight but leaves a request waiting', () => {
  const {focus, published, record} = harness({pendingTrackId: 'a'});
  focus.cancel();
  assert.deepEqual([record().pendingTrackId, record().focusGeneration, published], ['a', 1, []]);
});

test('the listener claiming the view ends any request and arc, and names the new view intent', () => {
  const {focus, published, record} = harness({pendingTrackId: 'a', frame: 3, viewIntent: 4});
  assert.equal(focus.claimView(), 5);
  assert.deepEqual([record().pendingTrackId, record().frame], [null, null]);
  assert.deepEqual(published.map(event => event.type), ['camera-focus-cancelled', 'camera-view-claimed']);
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
