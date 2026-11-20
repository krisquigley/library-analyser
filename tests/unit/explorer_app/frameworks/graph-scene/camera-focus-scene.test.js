// Issue #146: the camera focus's work on the vendored camera and Trackball controls.
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {
  animateCameraArc, createCameraControlsWatch, setCameraFocusPose, settleCameraFocusInput, showCameraArcPose,
} from '../../../../../music_explorer/frameworks/explorer/assets/app/frameworks/graph-scene/camera-focus-scene.js';
import {loadVendoredGraph, UNFLUSHED_INPUT, vendoredGraphScene} from './vendored-graph.js';

const vendor = loadVendoredGraph();
const SETTINGS = Object.freeze(['staticMoving', 'dynamicDampingFactor', 'rotateSpeed', 'zoomSpeed', 'panSpeed', 'noZoom', 'noPan',
  'noRotate', 'minDistance', 'maxDistance']);
const settingsOf = controls => Object.fromEntries(SETTINGS.map(name => [name, controls[name]]));

function manualStart() {
  const scene = vendoredGraphScene(vendor);
  scene.controls.target.set(120, -80, 30);
  scene.camera.position.set(400, -240, 180);
  scene.camera.up.set(0.2, 1, 0.3).normalize();
  Object.assign(scene.controls, {minDistance: 0.25, maxDistance: 2000});
  scene.controls.update();
  return scene;
}

const renderedPose = ({camera, controls}) => ({position: camera.position.clone(), target: controls.target.clone(),
  up: camera.up.clone(), quaternion: camera.quaternion.clone()});

function assertSamePose(actual, expected, label) {
  assert.ok(actual.position.distanceTo(expected.position) < 1e-9, `${label}: position`);
  assert.ok(actual.target.distanceTo(expected.target) < 1e-9, `${label}: target`);
  assert.ok(actual.up.distanceTo(expected.up) < 1e-10, `${label}: up`);
  assert.ok(actual.quaternion.angleTo(expected.quaternion) < 1e-7, `${label}: orientation`);
}

test('a focus pose is written at once, and keeps the orbit target in step even while the controls are disabled', () => {
  const {graph, camera, controls, state} = vendoredGraphScene(vendor);
  controls.enabled = false;
  setCameraFocusPose(graph, {x: 501, y: 402, z: 303}, {x: 51, y: 42, z: 33});
  assert.deepEqual([camera.position.x, controls.target.x, state.tweenGroup.getAll().length], [501, 51, 0]);
  const rendered = camera.quaternion.clone();
  controls.update();
  assert.ok(camera.quaternion.angleTo(rendered) < 1e-7, 'the next update keeps looking at the focused point');
});

test('settling drains a pending wheel, pan or orbit and restores the pose and settings, even blocked ones', () => {
  for (const input of Object.keys(UNFLUSHED_INPUT)) {
    for (const blocked of [false, true]) {
      const scene = manualStart();
      UNFLUSHED_INPUT[input](scene.controls);
      const config = {staticMoving: blocked, dynamicDampingFactor: 0.37, rotateSpeed: 1.3, zoomSpeed: 1.7, panSpeed: 0.6,
        noZoom: blocked, noPan: blocked, noRotate: blocked, minDistance: 0.25, maxDistance: 2000};
      Object.assign(scene.controls, config);
      const start = renderedPose(scene);
      settleCameraFocusInput(scene.graph);
      const label = `${input}${blocked ? ' blocked' : ''}`;
      assert.deepEqual(settingsOf(scene.controls), config, label);
      assertSamePose(renderedPose(scene), start, `${label} settled`);
      Object.assign(scene.controls, {staticMoving: false, noZoom: false, noPan: false, noRotate: false});
      const settled = renderedPose(scene);
      scene.controls.update();
      assert.ok(renderedPose(scene).position.distanceTo(settled.position) < 1e-6, `${label}: nothing left to apply`);
    }
  }
});

test('after settling, new wheel and pan input still moves the camera with the listener\'s own speeds', () => {
  const scene = manualStart();
  UNFLUSHED_INPUT.orbit(scene.controls);
  settleCameraFocusInput(scene.graph);
  const before = renderedPose(scene);
  UNFLUSHED_INPUT.wheel(scene.controls);
  assert.ok(scene.camera.position.distanceTo(before.position) > 1e-6, 'wheel');
  const wheeled = renderedPose(scene);
  UNFLUSHED_INPUT.pan(scene.controls);
  assert.ok(scene.controls.target.distanceTo(wheeled.target) > 1e-6, 'pan');
});

test('settling keeps an ordinary start pose and radius', () => {
  for (const input of ['wheel', 'pan']) {
    const scene = manualStart();
    UNFLUSHED_INPUT[input](scene.controls);
    const start = renderedPose(scene);
    const radius = scene.camera.position.distanceTo(scene.controls.target);
    settleCameraFocusInput(scene.graph);
    assertSamePose(renderedPose(scene), start, input);
    assert.ok(Math.abs(scene.camera.position.distanceTo(scene.controls.target) - radius) < 1e-9, input);
  }
});

test('settling restores the listener\'s settings even when the controls fail to update', () => {
  const scene = manualStart();
  const config = settingsOf(scene.controls);
  scene.controls.update = () => { throw new Error('controls failed'); };
  assert.throws(() => settleCameraFocusInput(scene.graph), /controls failed/);
  assert.deepEqual(settingsOf(scene.controls), config);
});

test('controls without an update are left alone', () => {
  const graph = {controls: () => ({}), camera: () => ({}), cameraPosition: () => assert.fail('nothing is written')};
  assert.doesNotThrow(() => settleCameraFocusInput(graph));
});

test('an arc pose turns the camera\'s up and writes the pose; without an up only the pose is written', () => {
  const {graph, camera, controls} = vendoredGraphScene(vendor);
  showCameraArcPose(graph, {position: {x: 0, y: 0, z: 50}, target: {x: 0, y: 0, z: 0}, up: {x: 1, y: 0, z: 0}});
  assert.deepEqual([camera.position.z, controls.target.z, camera.up.x, camera.up.y], [50, 0, 1, 0]);
  showCameraArcPose(graph, {position: {x: 0, y: 0, z: 60}, target: {x: 0, y: 0, z: 1}, up: null});
  assert.deepEqual([camera.position.z, controls.target.z, camera.up.x], [60, 1, 1]);
});

test('the listener starting to move the camera claims the view, and new controls replace the old ones', () => {
  const heard = [];
  const watch = createCameraControlsWatch({onControlsReplaced: () => heard.push('replaced'), onViewClaimed: () => heard.push('claimed')});
  const first = vendoredGraphScene(vendor);
  watch.observe(first.graph);
  watch.observe(first.graph);
  assert.deepEqual(heard, ['replaced']);
  first.controls.dispatchEvent({type: 'start'});
  assert.deepEqual(heard, ['replaced', 'claimed']);
  const second = vendoredGraphScene(vendor);
  watch.observe(second.graph);
  first.controls.dispatchEvent({type: 'start'});
  second.controls.dispatchEvent({type: 'start'});
  assert.deepEqual(heard, ['replaced', 'claimed', 'replaced', 'claimed']);
  watch.observe({});
  second.controls.dispatchEvent({type: 'start'});
  assert.deepEqual(heard, ['replaced', 'claimed', 'replaced', 'claimed', 'replaced']);
});

test('a graph without controls still takes a focus pose', () => {
  const written = [];
  setCameraFocusPose({cameraPosition: (...args) => written.push(args)}, {x: 1, y: 2, z: 3}, {x: 0, y: 0, z: 0});
  assert.deepEqual(written, [[{x: 1, y: 2, z: 3}, {x: 0, y: 0, z: 0}, 0]]);
});

// A plain camera and a focus use case stand-in that records the arc's timeline.
function arcHarness({running = () => true} = {}) {
  const camera = {position: {x: 0, y: 0, z: 100}, up: {x: 0, y: 1, z: 0, set(x, y, z) { Object.assign(this, {x, y, z}); }}};
  const controls = {target: {x: 0, y: 0, z: 0}};
  const graph = {camera: () => camera, controls: () => controls,
    cameraPosition(position) { if (!position) return {...camera.position}; Object.assign(camera.position, position); return graph; }};
  const timeline = [], pending = [];
  let clock = 1000;
  const cameraFocus = {begin: () => { timeline.push('begin'); return 7; }, frameRan: arc => { timeline.push(['ran', arc]); return running(); },
    frameScheduled: (arc, frame) => timeline.push(['scheduled', arc, frame]), finished: arc => timeline.push(['finished', arc])};
  const frames = {request: callback => { pending.push(callback); return pending.length; }, now: () => clock};
  const runFrame = at => { clock = at; pending.shift()(at); };
  return {graph, camera, controls, cameraFocus, frames, timeline, pending, runFrame};
}

test('the arc begins a focus, then draws a frame at a time until it lands after 700 ms', () => {
  const h = arcHarness();
  animateCameraArc(h.graph, {position: {x: 0, y: 0, z: 50}, target: {x: 10, y: 0, z: 0}}, {cameraFocus: h.cameraFocus, frames: h.frames, isShown: () => true});
  assert.deepEqual(h.timeline, ['begin', ['scheduled', 7, 1]]);
  h.runFrame(1350);
  assert.ok(h.controls.target.x > 0 && h.controls.target.x < 10, 'halfway, the camera is between the two poses');
  assert.deepEqual(h.timeline.slice(2), [['ran', 7], ['scheduled', 7, 1]]);
  h.runFrame(1700);
  assert.deepEqual(h.controls.target, {x: 10, y: 0, z: 0});
  assert.deepEqual(h.camera.position, {x: 0, y: 0, z: 50});
  assert.deepEqual(h.timeline.slice(-2), [['ran', 7], ['finished', 7]]);
  assert.equal(h.pending.length, 0);
});

test('a cancelled focus stops at its next frame and leaves the camera where it was', () => {
  const h = arcHarness({running: () => false});
  animateCameraArc(h.graph, {position: {x: 0, y: 0, z: 50}, target: {x: 10, y: 0, z: 0}}, {cameraFocus: h.cameraFocus, frames: h.frames, isShown: () => true});
  h.runFrame(1350);
  assert.deepEqual(h.controls.target, {x: 0, y: 0, z: 0});
  assert.equal(h.pending.length, 0);
});

test('a focus on a graph no longer shown stops without touching the camera', () => {
  const h = arcHarness();
  animateCameraArc(h.graph, {position: {x: 0, y: 0, z: 50}, target: {x: 10, y: 0, z: 0}}, {cameraFocus: h.cameraFocus, frames: h.frames, isShown: () => false});
  h.runFrame(1350);
  assert.deepEqual(h.controls.target, {x: 0, y: 0, z: 0});
  assert.ok(!h.timeline.some(entry => entry[0] === 'ran'), 'a replaced graph is not the focus\'s to draw');
});
