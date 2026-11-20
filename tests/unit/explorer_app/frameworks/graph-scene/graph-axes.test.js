// Issue #146: the mood axes in the 3D scene and their screen labels, redrawn only when the layout changes.
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {createGraphAxes} from '../../../../../music_explorer/frameworks/explorer/assets/app/frameworks/graph-scene/graph-axes.js';
import {fakeElement, installFakeDocument} from '../fake-document.js';

class Geometry { constructor(...size) { this.size = size; } dispose() { this.disposed = true; } }
class Material { constructor(properties) { Object.assign(this, properties); } dispose() { this.disposed = true; } }
class Mesh {
  constructor(geometry, material) {
    Object.assign(this, {geometry, material});
    this.position = {set: (...xyz) => { this.at = xyz; }};
    this.scale = {set: (...xyz) => { this.size = xyz; }};
  }
}
class Scene {
  constructor() { this.children = []; }
  add(child) { this.children.push(child); child.parent = this; }
  remove(child) { this.children = this.children.filter(each => each !== child); child.parent = null; }
}

function graphWithNode() {
  const scene = new Scene();
  const node = new Mesh(new Geometry(4), new Material({}));
  node.__graphObjType = 'node';
  scene.add(node);
  return {scene: () => scene, graph2ScreenCoords: (x, y) => ({x, y})};
}

const axis = (key, start, end, color = '#fff') => ({key, label: key.toUpperCase() + ' axis', color, references: ['0.1', '0.9'],
  start: {x: 0, y: 0, z: 0, ...start}, end: {x: 0, y: 0, z: 0, ...end}});
const SPEC = [axis('x', {x: 10}, {x: 110}), axis('y', {y: 20}, {y: 60}), axis('z', {z: 30}, {z: 90})];
const groups = graph => graph.scene().children.filter(child => child.name === 'mood-xyz-axes');

test('the axes join the scene once, built from the node meshes\' own classes, never pickable', () => {
  installFakeDocument([]);
  const graph = graphWithNode(), axes = createGraphAxes();
  const group = axes.sync(graph, SPEC, null);
  assert.deepEqual(groups(graph), [group]);
  assert.deepEqual(group.children.map(mesh => mesh.name), ['axis-x', 'axis-y', 'axis-z']);
  assert.ok(group.children.every(mesh => mesh instanceof Mesh && mesh.raycast() === undefined));
  assert.deepEqual(group.children[0].at, [60, 0, 0], 'each axis sits at its middle');
  assert.deepEqual(group.children[0].size, [50, 0.65, 0.65], 'and reaches both ends');
  assert.equal(group.children[0].material.opacity, 0.8);
});

test('the same layout keeps the same axes; a new one replaces and disposes them', () => {
  installFakeDocument([]);
  const graph = graphWithNode(), axes = createGraphAxes();
  const group = axes.sync(graph, SPEC, null);
  assert.strictEqual(axes.sync(graph, structuredClone(SPEC), null), group);
  const next = axes.sync(graph, [axis('x', {x: 0}, {x: 36})], null);
  assert.notStrictEqual(next, group);
  assert.deepEqual(groups(graph), [next]);
  assert.ok(group.children.every(mesh => mesh.geometry.disposed && mesh.material.disposed));
});

test('no axes without positioned tracks, or before the graph has drawn its nodes', () => {
  installFakeDocument([]);
  const graph = graphWithNode(), axes = createGraphAxes();
  axes.sync(graph, SPEC, null);
  assert.equal(axes.sync(graph, [], null), null);
  assert.deepEqual(groups(graph), []);
  const empty = {scene: () => new Scene()};
  assert.equal(createGraphAxes().sync(empty, SPEC, null), null);
});

test('each axis is labelled at its end with its name and at its start with its data range', () => {
  installFakeDocument([]);
  const host = fakeElement('div');
  createGraphAxes().sync(graphWithNode(), SPEC, host);
  assert.deepEqual(host.children.map(label => label.textContent),
    ['X axis', 'data 0.1–0.9', 'Y axis', 'data 0.1–0.9', 'Z axis', 'data 0.1–0.9']);
  assert.ok(host.children.every(label => label.className === 'graph-axis-label' && label.style.color === '#fff'));
});

test('labels follow the screen and hide when their point leaves the viewport', () => {
  installFakeDocument([]);
  const host = Object.assign(fakeElement('div'), {clientWidth: 100, clientHeight: 100});
  const graph = graphWithNode(), axes = createGraphAxes();
  axes.sync(graph, SPEC, host);
  axes.placeLabels(graph, host);
  const [xEnd, xStart] = host.children;
  assert.equal(xEnd.style.transform, 'translate(110px,0px) translate(-50%,-50%)');
  assert.equal(xEnd.style.display, 'none', 'x = 110 is past the right edge');
  assert.equal(xStart.style.display, '');
});

test('replaced axes take their labels with them', () => {
  installFakeDocument([]);
  const host = fakeElement('div'), graph = graphWithNode(), axes = createGraphAxes();
  axes.sync(graph, SPEC, host);
  const removed = [];
  for (const label of host.children) label.remove = () => removed.push(label.textContent);
  axes.sync(graph, [], host);
  assert.equal(removed.length, 6);
});
