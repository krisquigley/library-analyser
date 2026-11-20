// Issue #146: the translucent halo around the current track's node in the 3D scene.
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {
  createSelectedNodeHalo, findSceneObject, graphObjectTrackId,
} from '../../../../../music_explorer/frameworks/explorer/assets/app/frameworks/graph-scene/selected-node-halo.js';

class Geometry { constructor(radius) { this.radius = radius; } dispose() { this.disposed = true; } }
class Material { constructor(properties) { Object.assign(this, properties); } dispose() { this.disposed = true; } }
class Mesh {
  constructor(geometry, material) {
    this.geometry = geometry;
    this.material = material;
    this.userData = {};
    this.position = {x: 0, y: 0, z: 0, set(x, y, z) { Object.assign(this, {x, y, z}); }};
    this.scale = {x: 1, y: 1, z: 1};
  }
}

function sceneWith(...meshes) {
  let childReads = 0;
  const branch = {
    _children: [], parent: null,
    get children() { childReads++; return this._children; },
    add(child) { this._children.push(child); child.parent = this; },
    remove(child) { this._children = this._children.filter(each => each !== child); child.parent = null; },
  };
  const scene = {...branch, _children: [], isScene: true, get children() { childReads++; return this._children; }};
  scene.add(branch);
  meshes.forEach(mesh => branch.add(mesh));
  return {scene, branch, graph: {scene: () => scene}, childReads: () => childReads};
}

function nodeMesh(trackId, {radius = 4, position = [10, 20, 30]} = {}) {
  const mesh = new Mesh(new Geometry(radius), new Material({color: '#336699'}));
  mesh.__data = {id: trackId};
  mesh.position.set(...position);
  return mesh;
}

const node = (id, color = '#336699') => ({id, x: 1, y: 2, z: 3, color});
const halosIn = root => {
  const found = [];
  (function walk(object) { if (object.userData?.role === 'selected-node-halo') found.push(object); (object._children || []).forEach(walk); })(root);
  return found;
};

test('a scene object names its track by its graph data or user data', () => {
  assert.deepEqual([{__data: {id: 'a'}}, {userData: {trackId: 'b'}}, {userData: {track_id: 'c'}}, {__data: {node: {id: 'd'}}}, {}, null]
    .map(graphObjectTrackId), ['a', 'b', 'c', 'd', null, null]);
  const tree = {name: 'root', children: [{name: 'a', children: [{name: 'deep'}]}, {name: 'b'}]};
  assert.equal(findSceneObject(tree, object => object.name === 'deep').name, 'deep');
  assert.equal(findSceneObject(tree, object => object.name === 'none'), null);
});

test('the current node gets one translucent halo that cannot be picked, built from the node mesh', () => {
  const mesh = nodeMesh('a');
  const {scene, graph} = sceneWith(mesh);
  const halo = createSelectedNodeHalo().sync(graph, [node('a'), node('b')], 'a');
  assert.deepEqual(halosIn(scene), [halo]);
  assert.ok(halo instanceof Mesh);
  assert.ok(Math.abs(halo.geometry.radius / mesh.geometry.radius - 1.3) < 1e-9);
  assert.deepEqual([halo.material.transparent, halo.material.opacity, halo.material.depthWrite, halo.material.depthTest],
    [true, 0.25, false, false]);
  assert.notEqual(halo.material.color, '#336699');
  assert.deepEqual([halo.name, halo.userData.trackId], ['selected-node-halo', 'a']);
  const intersections = [];
  halo.raycast({}, intersections);
  assert.deepEqual(intersections, []);
  assert.deepEqual([halo.position.x, halo.position.y, halo.position.z], [10, 20, 30]);
});

test('a white node gets a warm halo so it still stands out', () => {
  const {graph} = sceneWith(nodeMesh('a'));
  assert.equal(createSelectedNodeHalo().sync(graph, [node('a', '#f8f7ff')], 'a').material.color, '#ffcc66');
});

test('another selection replaces the halo, and no selection or a hidden node removes it', () => {
  const {scene, graph} = sceneWith(nodeMesh('a'), nodeMesh('b', {position: [40, 50, 60]}));
  const marker = createSelectedNodeHalo();
  const first = marker.sync(graph, [node('a'), node('b')], 'a');
  const second = marker.sync(graph, [node('a'), node('b')], 'b');
  assert.deepEqual([halosIn(scene), first.geometry.disposed, first.material.disposed], [[second], true, true]);
  assert.equal(second.userData.trackId, 'b');
  assert.equal(marker.sync(graph, [node('a')], 'b'), null);
  assert.deepEqual(halosIn(scene), []);
  marker.sync(graph, [node('a')], 'a');
  assert.equal(marker.sync(graph, [node('a')], null), null);
  assert.deepEqual([halosIn(scene), marker.current()], [[], null]);
});

test('a steady selection reuses its halo without walking the scene again, and follows the node as it moves', () => {
  const mesh = nodeMesh('a');
  const {graph, childReads} = sceneWith(mesh);
  const marker = createSelectedNodeHalo();
  const first = marker.sync(graph, [node('a')], 'a');
  const reads = childReads();
  mesh.position.set(40, 50, 60);
  assert.equal(marker.sync(graph, [node('a')], 'a'), first);
  assert.equal(childReads(), reads);
  assert.deepEqual([first.position.x, first.position.y, first.position.z], [40, 50, 60]);
  assert.deepEqual([marker.current().trackId, marker.current().mesh], ['a', first]);
});

test('a node mesh that was replaced, or a halo that was disposed, is found and built again', () => {
  const mesh = nodeMesh('a');
  const {graph, branch} = sceneWith(mesh);
  const marker = createSelectedNodeHalo();
  const first = marker.sync(graph, [node('a')], 'a');
  branch.remove(mesh);
  branch.add(nodeMesh('a', {position: [70, 80, 90]}));
  const second = marker.sync(graph, [node('a')], 'a');
  assert.notEqual(second, first);
  assert.equal(second.position.x, 70);
  second.disposed = true;
  const third = marker.sync(graph, [node('a')], 'a');
  assert.notEqual(third, second);
  assert.equal(third.position.x, 70);
});

test('without a node mesh, a plain scene gets a stand-in halo at the node, and a real scene gets none', () => {
  const plain = {children: [], add(object) { this.children.push(object); }, remove() {}};
  const standIn = createSelectedNodeHalo().sync({scene: () => plain}, [node('a')], 'a');
  assert.deepEqual([standIn.name, standIn.position.x, standIn.position.y, standIn.position.z], ['selected-node-halo', 1, 2, 3]);
  const real = {children: [], isScene: true, add() { assert.fail('nothing is added'); }};
  assert.equal(createSelectedNodeHalo().sync({scene: () => real}, [node('a')], 'a'), null);
});

test('a graph without a scene has no halo', () => {
  const {scene, graph} = sceneWith(nodeMesh('a'));
  const marker = createSelectedNodeHalo();
  marker.sync(graph, [node('a')], 'a');
  assert.equal(marker.sync({}, [node('a')], 'a'), null);
  assert.deepEqual([halosIn(scene), marker.current()], [[], null]);
});

test('clearing removes the halo, so new graph data builds it afresh', () => {
  const {scene, graph} = sceneWith(nodeMesh('a'));
  const marker = createSelectedNodeHalo();
  const first = marker.sync(graph, [node('a')], 'a');
  marker.clear();
  assert.deepEqual([halosIn(scene), marker.current(), first.geometry.disposed], [[], null, true]);
  assert.notEqual(marker.sync(graph, [node('a')], 'a'), first);
  assert.doesNotThrow(() => createSelectedNodeHalo().clear());
});
