// Issue #146: what the vendored 3d-force-graph camera does, which the graph scene's camera code works around.
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {loadVendoredGraph, vendoredGraphScene} from './vendored-graph.js';

const vendor = loadVendoredGraph();

test('an instant camera setter does not cancel the vendor\'s own timed tweens, which later overwrite it', () => {
  const {camera, controls, state, advance} = vendoredGraphScene(vendor);
  vendor.cameraPosition(state, {x: 100, y: 0, z: 0}, {x: 20, y: 0, z: 0}, 700);
  advance(100);
  assert.equal(state.tweenGroup.getAll().length, 2);
  vendor.cameraPosition(state, {x: 5, y: 6, z: 7}, {x: 8, y: 9, z: 10}, 0);
  assert.equal(camera.position.x, 5);
  advance(200);
  assert.notEqual(camera.position.x, 5);
  assert.notEqual(controls.target.x, 8);
});

test('with the controls disabled, the vendor setter looks at the point but leaves the orbit target stale', () => {
  const {camera, controls, state} = vendoredGraphScene(vendor);
  controls.target.set(120, -80, 30);
  camera.position.set(400, -240, 180);
  controls.update();
  controls.enabled = false;
  const staleTarget = controls.target.clone();
  const target = {x: 51, y: 42, z: 33};
  vendor.cameraPosition(state, {x: 501, y: 402, z: 303}, target, 0);
  assert.ok(controls.target.distanceTo(staleTarget) < 1e-9);
  const looking = camera.clone();
  looking.lookAt(new vendor.THREE.Vector3(target.x, target.y, target.z));
  assert.ok(camera.quaternion.angleTo(looking.quaternion) < 1e-7);
  const rendered = camera.quaternion.clone();
  controls.update();
  assert.ok(camera.quaternion.angleTo(rendered) > 0.01, 'the next Trackball update turns back to the stale target');
});
