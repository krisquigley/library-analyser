// Issue #146: the camera's focus on the current track, from a request to the end of its arc.
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {
  CAMERA_FOCUS_STATES, CameraFocusTransitionError, cameraFocusState, nextCameraFocusState,
} from '../../../../music_explorer/frameworks/explorer/assets/app/domain/camera-focus.js';

test('the state is derived from what the camera is waiting for or doing', () => {
  assert.deepEqual(CAMERA_FOCUS_STATES, ['idle', 'pending', 'animating']);
  assert.equal(cameraFocusState({pendingTrackId: null, frame: null}), 'idle');
  assert.equal(cameraFocusState({pendingTrackId: 'a', frame: null}), 'pending');
  assert.equal(cameraFocusState({pendingTrackId: null, frame: 4}), 'animating');
});

test('a focus is requested from any state, and the listener claiming the view ends anything', () => {
  for (const state of CAMERA_FOCUS_STATES) {
    assert.equal(nextCameraFocusState(state, 'request'), 'pending', state);
    assert.equal(nextCameraFocusState(state, 'claim-view'), 'idle', state);
  }
});

test('a pending focus is taken: it animates, or is skipped when it cannot be shown', () => {
  assert.equal(nextCameraFocusState('pending', 'animate'), 'animating');
  assert.equal(nextCameraFocusState('pending', 'skip'), 'idle');
});

test('an arc runs frame by frame until it finishes or is cancelled; cancelling leaves a request waiting', () => {
  assert.equal(nextCameraFocusState('animating', 'next-frame'), 'animating');
  assert.equal(nextCameraFocusState('animating', 'finish'), 'idle');
  assert.equal(nextCameraFocusState('animating', 'cancel'), 'idle');
  assert.equal(nextCameraFocusState('idle', 'cancel'), 'idle');
  assert.equal(nextCameraFocusState('pending', 'cancel'), 'pending');
  assert.equal(nextCameraFocusState('idle', 'animate'), 'animating');
});

test('anything else is refused as a domain error', () => {
  assert.throws(() => nextCameraFocusState('idle', 'finish'), CameraFocusTransitionError);
  assert.throws(() => nextCameraFocusState('pending', 'next-frame'), /cannot next-frame while pending/);
  assert.throws(() => nextCameraFocusState('idle', 'skip'), CameraFocusTransitionError);
});
