// Issue #146: framing the graph's display coordinates for the camera.
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {graphCameraFrame} from '../../../../music_explorer/frameworks/explorer/assets/app/domain/camera-frame.js';

test('with no positioned node the camera looks at the origin from 650 away', () => {
  assert.deepEqual(graphCameraFrame([{x: NaN, y: 0, z: 0}], {width: 800, height: 600}, 50),
    {position: {x: 0, y: 0, z: 650}, target: {x: 0, y: 0, z: 0}});
});

test('the camera targets the centre of the nodes and backs off far enough to fit them', () => {
  const nodes = [{x: -100, y: -50, z: 0}, {x: 100, y: 50, z: 20}, {x: 5, y: 5, z: Infinity}];
  const frame = graphCameraFrame(nodes, {width: 1000, height: 500}, 50);
  assert.deepEqual(frame.target, {x: 0, y: 0, z: 10});
  const tanHalf = Math.tan(25 * Math.PI / 180);
  const expected = 10 + 4 + 1.2 * Math.max((50 + 4) / tanHalf, (100 + 4) / (tanHalf * 2));
  assert.ok(Math.abs(frame.position.z - (10 + expected)) < 1e-9);
  assert.deepEqual([frame.position.x, frame.position.y], [0, 0]);
});

test('a single node is never framed closer than 40, and a bad field of view or size falls back', () => {
  const frame = graphCameraFrame([{x: 1, y: 2, z: 3}], {width: 0, height: 0}, 500);
  assert.deepEqual(frame.target, {x: 1, y: 2, z: 3});
  assert.ok(frame.position.z - 3 >= 40);
  assert.deepEqual(graphCameraFrame([{x: 1, y: 2, z: 3}], {width: 1, height: 1}, 50), frame);
});
