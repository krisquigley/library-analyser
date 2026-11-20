// Issue #146 (#86): the 3D graph's drawing loop in the page: the vendor's public animation API, the view's pose,
// and the input that wakes it.
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {forceGraphRenderer, graphViewPose, observeGraphInput} from '../../../../../music_explorer/frameworks/explorer/assets/app/frameworks/graph-scene/force-graph-rendering.js';

test('the renderer pauses and resumes the current graph through its public animation API', () => {
  const calls = [];
  let graph = {pauseAnimation: () => calls.push('pause first'), resumeAnimation: () => calls.push('resume first')};
  const renderer = forceGraphRenderer(() => graph);
  renderer.pause();
  graph = {pauseAnimation: () => calls.push('pause second'), resumeAnimation: () => calls.push('resume second')};
  renderer.resume();
  assert.deepEqual(calls, ['pause first', 'resume second']);
  assert.equal(renderer.canPause(), true);
});

test('without a graph, or one with no animation API, nothing can pause and nothing breaks', () => {
  for (const graph of [null, {}]) {
    const renderer = forceGraphRenderer(() => graph);
    assert.equal(renderer.canPause(), false);
    assert.doesNotThrow(() => renderer.resume());
  }
});

test('the view pose changes when the camera, its orientation or the orbit target moves, and not otherwise', () => {
  const vector = (x, y, z, w) => ({x, y, z, w});
  const scene = {camera: {position: vector(0, 0, 100), quaternion: vector(0, 0, 0, 1), up: vector(0, 1, 0)}, target: vector(0, 0, 0)};
  const graph = {camera: () => scene.camera, controls: () => ({target: scene.target})};
  const still = graphViewPose(graph);
  assert.equal(graphViewPose(graph), still);
  for (const move of [() => { scene.camera.position.x = 1; }, () => { scene.camera.quaternion.w = 0.9; },
    () => { scene.camera.up.y = -1; }, () => { scene.target.z = 5; }]) {
    const before = graphViewPose(graph);
    move();
    assert.notEqual(graphViewPose(graph), before);
  }
  assert.equal(typeof graphViewPose({}), 'string');
});

test('pointer and wheel input on the graph wakes it, without blocking scrolling or waiting for bubbling', () => {
  const listened = [];
  const element = {addEventListener: (type, handler, options) => listened.push({type, handler, options})};
  let woken = 0;
  observeGraphInput(element, () => { woken++; });
  assert.deepEqual(listened.map(({type, options}) => [type, options]),
    ['pointerdown', 'pointermove', 'wheel'].map(type => [type, {capture: true, passive: true}]));
  listened.forEach(({handler}) => handler({}));
  assert.equal(woken, 3);
  assert.doesNotThrow(() => observeGraphInput(null, () => {}));
});
