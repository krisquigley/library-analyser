// Issue #146: the camera's focus arc and the poses it aims for.
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {
  CAMERA_FOCUS_MS, cameraArcPose, cameraFocusArc, cameraUnitDirection, cameraViewDirection, focusProgress, pickedNodePose,
  selectionFocusPose,
} from '../../../../music_explorer/frameworks/explorer/assets/app/domain/camera-arc.js';

const close = (actual, expected, label) => {
  for (const axis of ['x', 'y', 'z']) assert.ok(Math.abs(actual[axis] - expected[axis]) < 1e-9, `${label} ${axis}: ${actual[axis]}`);
};

test('a direction is a unit vector, even from huge or tiny components, and none for zero or non-finite', () => {
  close(cameraUnitDirection({x: 3, y: 0, z: 4}), {x: 0.6, y: 0, z: 0.8}, 'ordinary');
  close(cameraUnitDirection({x: Number.MAX_VALUE, y: Number.MAX_VALUE, z: 0}), {x: Math.SQRT1_2, y: Math.SQRT1_2, z: 0}, 'huge');
  close(cameraUnitDirection({x: 5e-324, y: 0, z: 0}), {x: 1, y: 0, z: 0}, 'subnormal');
  assert.equal(cameraUnitDirection({x: 0, y: 0, z: 0}), null);
  assert.equal(cameraUnitDirection({x: NaN, y: 0, z: 1}), null);
});

test('the view direction points from the target to the camera, even when the subtraction overflows', () => {
  close(cameraViewDirection({x: 0, y: 0, z: 10}, {x: 0, y: 0, z: 0}), {x: 0, y: 0, z: 1}, 'ordinary');
  close(cameraViewDirection({x: Number.MAX_VALUE, y: 0, z: 0}, {x: -Number.MAX_VALUE, y: 0, z: 0}), {x: 1, y: 0, z: 0}, 'overflow');
  assert.equal(cameraViewDirection({x: 1, y: 1, z: 1}, {x: 1, y: 1, z: 1}), null);
});

test('the arc starts at the camera, ends exactly on the requested pose, and keeps its radius in between', () => {
  const arc = cameraFocusArc({fromPosition: {x: 0, y: 0, z: 100}, fromTarget: {x: 0, y: 0, z: 0}, fromUp: {x: 0, y: 1, z: 0},
    position: {x: 110, y: 0, z: 0}, target: {x: 10, y: 0, z: 0}});
  close(cameraArcPose(arc, 0).position, {x: 0, y: 0, z: 100}, 'start');
  const end = cameraArcPose(arc, 1);
  assert.deepEqual([end.position, end.target], [{x: 110, y: 0, z: 0}, {x: 10, y: 0, z: 0}]);
  const middle = cameraArcPose(arc, 0.5);
  close(middle.target, {x: 5, y: 0, z: 0}, 'middle target');
  const radius = Math.hypot(...['x', 'y', 'z'].map(axis => middle.position[axis] - middle.target[axis]));
  assert.ok(Math.abs(radius - 100) < 1e-9);
  close(middle.up, {x: 0, y: 1, z: 0}, 'up stays level on a level turn');
});

test('turning to face the opposite way picks a plane across the up direction, and no up means none is turned', () => {
  const arc = cameraFocusArc({fromPosition: {x: 0, y: 0, z: 10}, fromTarget: {x: 0, y: 0, z: 0}, fromUp: null,
    position: {x: 0, y: 0, z: -10}, target: {x: 0, y: 0, z: 0}});
  const middle = cameraArcPose(arc, 0.5);
  close(middle.position, {x: 10, y: 0, z: 0}, 'through the side');
  assert.equal(middle.up, null);
});

test('progress runs from 0 to 1 over the focus time', () => {
  assert.equal(CAMERA_FOCUS_MS, 700);
  assert.deepEqual([focusProgress(100, 50), focusProgress(100, 450), focusProgress(100, 5000)], [0, 0.5, 1]);
});

test('a selection is focused from the bounded radius along its direction from the origin', () => {
  const pose = selectionFocusPose({x: 0, y: 30, z: 40}, {currentDirection: () => assert.fail('only an origin asks')});
  close(pose.position, {x: 0, y: 90, z: 120}, 'radial');
  assert.deepEqual(pose.target, {x: 0, y: 30, z: 40});
  assert.deepEqual(selectionFocusPose({x: 0, y: 0, z: 10}, {currentDirection: () => null, minDistance: 0, maxDistance: 20}).position,
    {x: 0, y: 0, z: 30});
  assert.deepEqual(selectionFocusPose({x: 0, y: 0, z: 0}, {currentDirection: () => ({x: 1, y: 0, z: 0})}).position, {x: 100, y: 0, z: 0});
  assert.deepEqual(selectionFocusPose({x: 0, y: 0, z: 0}, {currentDirection: () => null}).position, {x: 0, y: 0, z: 100});
});

test('a selection that cannot be focused reliably is left where it is', () => {
  const view = {currentDirection: () => null};
  assert.equal(selectionFocusPose({x: NaN, y: 0, z: 0}, view), null);
  assert.equal(selectionFocusPose({x: Number.MAX_VALUE, y: Number.MAX_VALUE, z: 0}, view), null);
  assert.equal(selectionFocusPose({x: 0, y: 0, z: 1}, {...view, maxDistance: 1e-200}), null);
});

test('a picked node keeps the camera\'s current offset, unless that offset cannot be represented', () => {
  const view = {cameraPosition: {x: 10, y: 0, z: 100}, orbitTarget: {x: 10, y: 0, z: 0}};
  assert.deepEqual(pickedNodePose({x: 1, y: 2, z: 3}, view), {position: {x: 1, y: 2, z: 103}, target: {x: 1, y: 2, z: 3}});
  assert.equal(pickedNodePose({x: 0, y: 0, z: 1e20}, view), null);
  assert.equal(pickedNodePose({x: NaN, y: 0, z: 0}, view), null);
});
