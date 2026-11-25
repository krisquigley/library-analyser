// Issue #146: framing the graph's display coordinates for the camera.
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {graphCameraFrame, neighbourhoodCameraDistance} from '../../../../music_explorer/frameworks/explorer/assets/app/domain/camera-frame.js';

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

// #267: a selection is framed so every neighbour linked to it stays in view, as the camera sees it from its direction.
const SQUARE = {width: 800, height: 800};
const FROM_FRONT = {x: 0, y: 0, z: 1};
const view = (changes = {}) => ({direction: FROM_FRONT, size: SQUARE, fieldOfView: 60, ...changes});
const TAN_30 = Math.tan(Math.PI / 6);

test("a selection backs off just far enough that its widest neighbour, node and padding, fits the field of view", () => {
  const centre = {x: 10, y: 0, z: 0};
  const distance = neighbourhoodCameraDistance(centre, [{x: 40, y: 0, z: 0}, {x: 10, y: -100, z: 0}], view());
  assert.ok(Math.abs(distance - 1.2 * (100 + 4) / TAN_30) < 1e-9, String(distance));
});

test("a neighbour behind the selection, along the line of sight, needs no more room than its sideways offset", () => {
  const behind = neighbourhoodCameraDistance({x: 0, y: 0, z: 0}, [{x: 0, y: 50, z: -900}], view());
  assert.equal(behind, 100, 'it already shows close to the selection from in front');
  const before = neighbourhoodCameraDistance({x: 0, y: 0, z: 0}, [{x: 0, y: 50, z: 100}], view());
  assert.ok(Math.abs(before - (100 + 1.2 * 54 / TAN_30)) < 1e-9, 'a neighbour nearer the camera keeps in front of it');
});

test("a narrow or portrait viewport backs further off than a wide one, by its narrower field of view", () => {
  const near = [{x: 0, y: 0, z: 0}, [{x: 50, y: 0, z: 0}]];
  const wide = neighbourhoodCameraDistance(...near, view({size: {width: 1600, height: 800}, fieldOfView: 50}));
  const square = neighbourhoodCameraDistance(...near, view({fieldOfView: 50}));
  const portrait = neighbourhoodCameraDistance(...near, view({size: {width: 400, height: 800}, fieldOfView: 50}));
  assert.equal(wide, square, 'the vertical field is the narrower one on a wide screen');
  assert.ok(portrait > square * 1.5, `${portrait} vs ${square}`);
});

test("close neighbours are never framed closer than the focus radius of 100, where the enlarged selected node still leaves room, and a track without positioned neighbours has no framing", () => {
  assert.equal(neighbourhoodCameraDistance({x: 0, y: 0, z: 0}, [{x: 1, y: 0, z: 0}], view()), 100);
  assert.equal(neighbourhoodCameraDistance({x: 0, y: 0, z: 0}, [], view()), null);
  assert.equal(neighbourhoodCameraDistance({x: 0, y: 0, z: 0}, [{x: NaN, y: 0, z: 0}], view()), null);
  assert.equal(neighbourhoodCameraDistance({x: 0, y: 0, z: 0}, [{x: 100, y: 0, z: 0}], view({size: {width: 0, height: 0}, fieldOfView: 'wide'})),
    neighbourhoodCameraDistance({x: 0, y: 0, z: 0}, [{x: 100, y: 0, z: 0}], view({fieldOfView: 50})), 'a bad size or field of view falls back');
});
