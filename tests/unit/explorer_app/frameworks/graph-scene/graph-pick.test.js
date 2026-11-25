// Issue #146: a click on a node in the 3D graph, and the camera's immediate move to it.
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {
  jumpCameraToPickedNode, mountedPickedNode, pickedTrackId,
} from '../../../../../music_explorer/frameworks/explorer/assets/app/frameworks/graph-scene/graph-pick.js';
import {loadVendoredGraph, UNFLUSHED_INPUT, vendoredGraphScene} from './vendored-graph.js';

const vendor = loadVendoredGraph();
const shown = (id, x, y, z) => ({id, x, y, z, fx: x, fy: y, fz: z});

test('a pick names a track only by a non-empty string id', () => {
  assert.deepEqual([{id: 'a'}, {id: ''}, {id: 7}, {}, null, undefined].map(pickedTrackId), ['a', null, null, null, null, null]);
});

test('the picked node is the mounted one, and only while it is still visible', () => {
  const mounted = [shown('a', 1, 2, 3)];
  assert.equal(mountedPickedNode('a', {visible: [shown('a', 9, 9, 9)], mounted}), mounted[0]);
  assert.equal(mountedPickedNode('a', {visible: [], mounted}), null, 'hidden by a filter');
  assert.equal(mountedPickedNode('b', {visible: [shown('b', 4, 5, 6)], mounted}), null, 'visible but not yet mounted');
});

function watchSpy() {
  const observed = [];
  return {observed, observe: graph => observed.push(graph)};
}

test('without neighbours the camera keeps its offset and moves at once to the picked node, after settling pending input', () => {
  const scene = vendoredGraphScene(vendor);
  scene.controls.target.set(10, 20, 30);
  scene.camera.position.set(110, 20, 30);
  UNFLUSHED_INPUT.wheel(scene.controls);
  const offset = scene.camera.position.clone().sub(scene.controls.target);
  const watch = watchSpy();
  assert.equal(jumpCameraToPickedNode(scene.graph, shown('a', 100, -50, 7), {controlsWatch: watch}), 'moved');
  assert.deepEqual([...scene.controls.target.toArray()], [100, -50, 7]);
  assert.ok(scene.camera.position.clone().sub(scene.controls.target).distanceTo(offset) < 1e-9);
  assert.equal(scene.state.tweenGroup.getAll().length, 0, 'no vendor tween to overwrite it later');
  assert.deepEqual(watch.observed, [scene.graph]);
  const settled = scene.camera.position.clone();
  scene.controls.update();
  assert.ok(scene.camera.position.distanceTo(settled) < 1e-6, 'the pending wheel was drained');
});

test('a node the camera cannot reach reliably leaves the camera where it is', () => {
  const scene = vendoredGraphScene(vendor);
  scene.camera.position.set(0, 0, 100);
  const before = scene.camera.position.clone();
  const watch = watchSpy();
  for (const node of [shown('a', NaN, 0, 0), shown('b', 0, 0, 1e200)]) {
    assert.equal(jumpCameraToPickedNode(scene.graph, node, {controlsWatch: watch}), 'skipped');
  }
  assert.deepEqual([scene.camera.position.distanceTo(before), watch.observed], [0, []]);
});

test('a camera that fails, or a graph without controls, is reported rather than thrown', () => {
  const scene = vendoredGraphScene(vendor);
  scene.graph.cameraPosition = position => { if (position) throw new Error('camera failed'); return {x: 0, y: 0, z: 100}; };
  assert.equal(jumpCameraToPickedNode(scene.graph, shown('a', 1, 2, 3), {controlsWatch: watchSpy()}), 'failed');
  const noControls = {cameraPosition: () => ({x: 0, y: 0, z: 100})};
  assert.equal(jumpCameraToPickedNode(noControls, shown('a', 1, 2, 3), {controlsWatch: watchSpy()}), 'failed');
});

test("with neighbours, the camera moves along its offset to the distance that keeps them all in view (#267)", () => {
  const scene = vendoredGraphScene(vendor);
  Object.assign(scene.graph, {width: () => 800, height: () => 800});
  scene.camera.fov = 60;
  scene.controls.target.set(0, 0, 0);
  scene.camera.position.set(0, 0, 500);
  const neighbours = [{x: 0, y: 100, z: 0}];
  assert.equal(jumpCameraToPickedNode(scene.graph, shown('a', 0, 0, 0), {controlsWatch: watchSpy(), neighbours}), 'moved');
  const expected = 1.2 * 104 / Math.tan(Math.PI / 6);
  assert.ok(Math.abs(scene.camera.position.z - expected) < 1e-6, String(scene.camera.position.z));
  assert.equal(scene.camera.position.x, 0);
});
