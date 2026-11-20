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

test('framing uses display coordinates, never the native axis values, and changes no node', () => {
  const node = Object.freeze({x: 72, y: 36, z: 180, fx: 72, fy: 36, fz: 180,
    axis: Object.freeze({x: Object.freeze({raw: -2}), y: Object.freeze({raw: 10}), z: Object.freeze({raw: 120})})});
  const before = JSON.stringify(node);
  assert.deepEqual(graphCameraFrame([node], {width: 800, height: 600}, 50).target, {x: 72, y: 36, z: 180});
  assert.equal(JSON.stringify(node), before);
});

test('a portrait viewport or a narrow field of view backs the camera further off', () => {
  const nodes = [{x: -100, y: -10, z: 0}, {x: 100, y: 10, z: 0}];
  const distance = (size, fov) => graphCameraFrame(nodes, size, fov).position.z;
  assert.ok(distance({width: 500, height: 1000}, 50) > distance({width: 1000, height: 500}, 50));
  assert.ok(distance({width: 1000, height: 500}, 20) > distance({width: 1000, height: 500}, 50));
});

test('an origin node is framed from a finite, real distance whatever the field of view', () => {
  for (const fov of [NaN, 0, 180]) {
    const {position, target} = graphCameraFrame([{x: 0, y: 0, z: 0}], {width: 800, height: 600}, fov);
    assert.deepEqual(target, {x: 0, y: 0, z: 0});
    assert.ok(Number.isFinite(position.z) && position.z > 0, `${fov}: ${position.z}`);
  }
});

test('nodes without numeric coordinates do not move the frame', () => {
  const placed = {x: 10, y: 20, z: 30};
  const frame = graphCameraFrame([placed], {width: 800, height: 600}, 50);
  for (const x of [undefined, null, '0']) {
    assert.deepEqual(graphCameraFrame([placed, {x, y: 500, z: 500}], {width: 800, height: 600}, 50), frame, String(x));
  }
});
