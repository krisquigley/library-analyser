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

const AXES = ['x', 'y', 'z'];
const NODE_A = Object.freeze({x: 50, y: -80, z: 120});
const ORIGIN = Object.freeze({x: 0, y: 0, z: 0});
const offsetLength = pose => Math.hypot(...AXES.map(axis => pose.position[axis] - pose.target[axis]));
const finite = pose => AXES.every(axis => Number.isFinite(pose.position[axis]) && Number.isFinite(pose.target[axis]));
const steps = Array.from({length: 141}, (_, index) => index * 5 / 700).map(progress => Math.min(1, progress));
const arcTo = (end, from) => cameraFocusArc({fromUp: {x: 0, y: 1, z: 0}, ...from, ...end});

test('a focus path stays within the orbit bounds the whole way', () => {
  for (const [minDistance, maxDistance, startRadius] of [[250, 600, 400], [10, 60, 40]]) {
    const end = selectionFocusPose(NODE_A, {currentDirection: () => assert.fail('not an origin'), minDistance, maxDistance});
    const expected = Math.max(minDistance, Math.min(maxDistance, 100));
    assert.ok(Math.abs(offsetLength(end) - expected) < 1e-9, `end radius ${offsetLength(end)}`);
    const arc = arcTo(end, {fromPosition: {x: 0, y: 0, z: startRadius}, fromTarget: ORIGIN});
    const [low, high] = [Math.min(startRadius, expected), Math.max(startRadius, expected)];
    for (const progress of steps) {
      const radius = offsetLength(cameraArcPose(arc, progress));
      assert.ok(radius >= low - 1e-9 && radius <= high + 1e-9, `radius ${radius} at ${progress}`);
    }
  }
});

test('a positioned origin keeps the current view direction at a bounded radius', () => {
  const along = {x: 0.6, y: 0, z: 0.8};
  for (const [bounds, radius] of [[{minDistance: 250, maxDistance: 600}, 250], [{minDistance: 10, maxDistance: 60}, 60],
    [{minDistance: 0, maxDistance: 60}, 60]]) {
    const pose = selectionFocusPose(ORIGIN, {currentDirection: () => along, ...bounds});
    close(pose.position, {x: 0.6 * radius, y: 0, z: 0.8 * radius}, `radius ${radius}`);
  }
});

test('an arc from an exceptional or overflowing radius stays finite and ends exactly on the pose', () => {
  const end = selectionFocusPose(NODE_A, {currentDirection: () => null});
  for (const fromPosition of [{x: 0, y: 0, z: 1e200}, {x: Number.MAX_VALUE, y: Number.MAX_VALUE, z: 0},
    {x: 1e300, y: -1e300, z: 1e300}]) {
    const arc = arcTo(end, {fromPosition, fromTarget: {x: -fromPosition.x / 2, y: 0, z: 0}});
    for (const progress of steps) {
      const pose = cameraArcPose(arc, progress);
      assert.ok(finite(pose), `finite at ${progress} from ${fromPosition.x}`);
      assert.ok(offsetLength(pose) > 0, `a real offset at ${progress}`);
    }
    assert.deepEqual(cameraArcPose(arc, 1).position, end.position);
    assert.deepEqual(cameraArcPose(arc, 1).target, end.target);
  }
});

test('an arc from a subnormal camera gap stays finite and ends at the focus radius', () => {
  const end = selectionFocusPose(NODE_A, {currentDirection: () => null});
  const arc = arcTo(end, {fromPosition: {x: 5e-324, y: 0, z: 0}, fromTarget: ORIGIN});
  for (const progress of steps) assert.ok(finite(cameraArcPose(arc, progress)), `finite at ${progress}`);
  assert.ok(Math.abs(offsetLength(cameraArcPose(arc, 1)) - 100) < 1e-9);
});

test('the view turns smoothly from any manual orbit, without a flip between frames or a roll', () => {
  const end = selectionFocusPose(ORIGIN, {currentDirection: () => ({x: 1, y: 0, z: 0})});
  const dot = (a, b) => AXES.reduce((sum, axis) => sum + a[axis] * b[axis], 0);
  for (const [fromPosition, fromUp] of [[{x: 0, y: 0, z: 100}, {x: 0, y: 1, z: 0}], [{x: 0, y: 100, z: 0}, {x: 0, y: 0, z: -1}],
    [{x: -100, y: 0, z: 0}, {x: 0, y: 1, z: 0}], [{x: 30, y: -90, z: -20}, cameraUnitDirection({x: 90, y: 30, z: 0})]]) {
    const arc = arcTo(end, {fromPosition, fromTarget: ORIGIN, fromUp});
    let previous = null;
    for (const progress of steps) {
      const pose = cameraArcPose(arc, progress);
      const view = cameraViewDirection(pose.position, pose.target);
      if (previous) {
        const turn = Math.acos(Math.max(-1, Math.min(1, AXES.reduce((sum, axis) => sum + view[axis] * previous[axis], 0))));
        assert.ok(turn < 0.05, `turn ${turn} at ${progress} from ${JSON.stringify(fromPosition)}`);
      }
      assert.ok(Math.abs(Math.hypot(pose.up.x, pose.up.y, pose.up.z) - 1) < 1e-9, `unit up at ${progress}`);
      assert.ok(Math.abs(dot(pose.up, view)) < 1e-9, `up stays square to the view at ${progress}`);
      previous = view;
    }
    assert.deepEqual(cameraArcPose(arc, 1).position, end.position);
  }
});

test('a focus whose offset cannot be squared reliably is skipped', () => {
  const along = () => ({x: 0, y: 0, z: 1});
  const diagonal = () => ({x: Math.sqrt(1 / 3), y: Math.sqrt(1 / 3), z: Math.sqrt(1 / 3)});
  for (const [coordinate, bounds, currentDirection] of [
    [0, {minDistance: 0, maxDistance: 1e-200}, along],
    [0, {minDistance: 0, maxDistance: Number.MIN_VALUE}, along],
    [0, {minDistance: 0, maxDistance: Math.sqrt(Number.MIN_VALUE)}, along],
    [0, {minDistance: 0, maxDistance: 2e-162}, along],
    [1e-200, {minDistance: 0, maxDistance: 1e-200}, along],
    [1e-161, {minDistance: 0, maxDistance: 1e-162}, along],
    [0, {minDistance: 1e200, maxDistance: Infinity}, along],
    [0, {minDistance: 0, maxDistance: 3e-162}, diagonal],
  ]) {
    assert.equal(selectionFocusPose({x: coordinate, y: 0, z: 0}, {currentDirection, ...bounds}), null,
      `${coordinate} within ${JSON.stringify(bounds)}`);
  }
});

test('a focus whose offset is lost beside the node, or is zero, is skipped; a tiny one that survives is kept', () => {
  for (const maxDistance of [0, 5e-324, 1e-15]) {
    assert.equal(selectionFocusPose(NODE_A, {currentDirection: () => null, minDistance: 0, maxDistance}), null, `${maxDistance}`);
  }
  const tiny = selectionFocusPose(NODE_A, {currentDirection: () => null, minDistance: 0, maxDistance: 1e-12});
  assert.ok(Math.abs(offsetLength(tiny) - 1e-12) < 2e-14, `radius ${offsetLength(tiny)}`);
});

test('a tiny node or a radius near the smallest normal square is still focused, along its direction', () => {
  const radius = Math.sqrt(2 ** -1022) * (1 + 1e-8);
  const diagonal = selectionFocusPose(ORIGIN, {currentDirection: () => ({x: Math.sqrt(1 / 3), y: Math.sqrt(1 / 3), z: Math.sqrt(1 / 3)}),
    minDistance: 0, maxDistance: radius});
  for (const axis of AXES) assert.ok(Math.abs(diagonal.position[axis] / (radius / Math.sqrt(3)) - 1) < 1e-12, axis);
  assert.deepEqual(selectionFocusPose({x: Number.MIN_VALUE, y: 0, z: 0}, {currentDirection: () => null, minDistance: 0, maxDistance: 2000}),
    {position: {x: 100, y: 0, z: 0}, target: {x: Number.MIN_VALUE, y: 0, z: 0}});
  for (const [coordinate, maxDistance] of [[1e-200, radius], [Number.MIN_VALUE, 0.5], [Number.MIN_VALUE * 200, 0.001],
    [Number.MIN_VALUE, 1e-100], [1e-200, 1e-150]]) {
    const pose = selectionFocusPose({x: coordinate, y: 0, z: 0}, {currentDirection: () => null, minDistance: 0, maxDistance});
    assert.ok(Math.abs((pose.position.x - coordinate) / maxDistance - 1) < 1e-12, `${coordinate} at ${maxDistance}`);
    assert.deepEqual([pose.position.y, pose.position.z], [0, 0]);
  }
});
