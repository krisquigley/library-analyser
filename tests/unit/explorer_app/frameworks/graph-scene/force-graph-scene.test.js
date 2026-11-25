// Issue #146: the 3D graph in the page: its vendor configuration, size, data, framing and canvas fallback.
import {test, afterEach} from 'node:test';
import assert from 'node:assert/strict';
import {
  configureForceGraph, createGraphDataMount, createGraphFraming, drawCanvasFallback, fitGraphToElement, graphContainer,
  graphDimensions, observeElementResize, selectedTrackNodeSize,
} from '../../../../../music_explorer/frameworks/explorer/assets/app/frameworks/graph-scene/force-graph-scene.js';

afterEach(() => { delete globalThis.document; delete globalThis.getComputedStyle; delete globalThis.ResizeObserver; delete globalThis.window; });

// A ForceGraph stand-in that records every setting, as the vendor's chainable API takes them.
function recordingGraph() {
  const settings = {};
  const calls = [];
  const graph = new Proxy({}, {get: (target, key) => {
    if (key in target) return target[key];
    return (...args) => { calls.push([key, ...args]); settings[key] = args[0]; return graph; };
  }});
  return {graph, settings, calls, named: name => calls.filter(([key]) => key === name)};
}

test('the graph is configured for fixed positions, sized nodes and relatedness-shaded links', () => {
  const {graph, settings} = recordingGraph();
  const handlers = {nodeLabel: () => 'node', linkLabel: () => 'link', linkColor: () => 'rgba(240,240,240,0.45)',
    linkWidth: () => 1.5, nodeValue: node => (node.id === 'a' ? 4 : 1), onNodeClick: () => 'clicked'};
  assert.equal(configureForceGraph(graph, handlers), graph);
  assert.deepEqual([settings.enableNodeDrag, settings.cooldownTicks, settings.nodeId, settings.nodeRelSize, settings.linkOpacity],
    [false, 0, 'id', 4, 1]);
  assert.deepEqual([settings.nodeLabel, settings.linkLabel, settings.linkColor, settings.linkWidth, settings.nodeVal,
    settings.onNodeClick],
  [handlers.nodeLabel, handlers.linkLabel, handlers.linkColor, handlers.linkWidth, handlers.nodeValue, handlers.onNodeClick]);
  assert.equal(settings.nodeColor({color: '#123456'}), '#123456');
});

test('the current track\'s node is drawn larger than the rest, without changing its colour', () => {
  let current = 'a';
  const size = selectedTrackNodeSize(() => current);
  assert.deepEqual([size({id: 'a'}), size({id: 'b'})], [4, 1]);
  current = 'b';
  assert.deepEqual([size({id: 'a'}), size({id: 'b'})], [1, 4]);
});

test('the graph fills its panel inside the padding and border, never smaller than a pixel', () => {
  globalThis.getComputedStyle = () => ({paddingLeft: '10px', paddingRight: '10px', borderLeftWidth: '1px', borderRightWidth: '1.5px'});
  assert.deepEqual(graphDimensions({clientHeight: 600.7, parentElement: {clientWidth: 800}}), {width: 777, height: 600});
  delete globalThis.getComputedStyle;
  assert.deepEqual(graphDimensions({clientWidth: 0, clientHeight: 0, parentElement: null}), {width: 900, height: 1040});
  assert.deepEqual(graphDimensions({clientWidth: 0.4, clientHeight: 0.2}), {width: 1, height: 1});
  globalThis.getComputedStyle = () => ({paddingLeft: '2000px'});
  assert.deepEqual(graphDimensions({clientHeight: 10, parentElement: {clientWidth: 800}}), {width: 1, height: 10});
});

const nodeAt = (id, x, y, z, extra = {}) => ({id, x, y, z, fx: x, fy: y, fz: z, ...extra});

test('graph data is handed over once, as a copy, and only again when the nodes or links change', () => {
  const {graph, named} = recordingGraph();
  const replaced = [];
  const mount = createGraphDataMount({onReplaced: () => replaced.push(named('graphData').length)});
  const data = {nodes: [nodeAt('a', 1, 2, 3), nodeAt('b', 4, 5, 6)], links: [{source: 'a', target: 'b', score: 0.5}]};
  mount.mount(graph, data);
  const [[, handed]] = named('graphData');
  assert.deepEqual(handed, data);
  assert.notEqual(handed.nodes[0], data.nodes[0]);
  assert.equal(mount.current(), handed);
  mount.mount(graph, {nodes: data.nodes.map(node => ({...node})), links: data.links});
  assert.equal(named('graphData').length, 1);
  mount.mount(graph, {...data, links: [{source: 'a', target: 'b', score: 0.9}]});
  assert.deepEqual([named('graphData').length, replaced], [2, [0, 1]]);
});

test('unchanged graph data takes the new mood scores and axes on the nodes already shown, even if some are gone', () => {
  const {graph} = recordingGraph();
  const mount = createGraphDataMount({onReplaced() {}});
  mount.mount(graph, {nodes: [nodeAt('a', 1, 2, 3, {moodScore: {raw: 0.1}})], links: []});
  assert.doesNotThrow(() => mount.mount(graph, {nodes: [nodeAt('a', 1, 2, 3, {moodScore: {raw: 0.9}, axis: {x: 'new'}})], links: []}));
  assert.deepEqual([mount.current().nodes[0].moodScore, mount.current().nodes[0].axis], [{raw: 0.9}, {x: 'new'}]);
  assert.doesNotThrow(() => mount.mount(graph, {nodes: [], links: []}));
});

test('every mount holds the layout fixed in three dimensions', () => {
  const {graph, settings} = recordingGraph();
  createGraphDataMount({onReplaced() {}}).mount(graph, {nodes: [], links: []});
  assert.deepEqual([settings.numDimensions, settings.d3AlphaDecay, settings.d3VelocityDecay], [3, 1, 1]);
});

function cameraGraph() {
  const calls = [];
  const controls = {target: {x: 90, y: 80, z: 70}};
  const graph = {camera: () => ({fov: 60}), controls: () => controls,
    cameraPosition: (position, target, duration) => calls.push({position, target, duration})};
  return {graph, calls, controls};
}

test('the camera frames a new layout at once, and leaves the listener\'s view alone while the layout stays', () => {
  const {graph, calls, controls} = cameraGraph();
  const reframed = [];
  const framing = createGraphFraming({onReframe: () => reframed.push(calls.length)});
  assert.equal(framing.layout(), null);
  const nodes = [nodeAt('a', 0, 0, 0), nodeAt('b', 100, 50, 20)];
  framing.frame(graph, nodes, {width: 1000, height: 500});
  assert.deepEqual([calls.length, calls[0].duration, reframed], [1, 0, [0]]);
  assert.deepEqual(calls[0].target, {x: 50, y: 25, z: 10});
  assert.deepEqual(controls.target, {x: 50, y: 25, z: 10});
  framing.frame(graph, [nodes[1], nodes[0]], {width: 400, height: 900});
  assert.equal(calls.length, 1, 'the same layout in another order, or a resize, keeps the view');
  framing.frame(graph, [nodes[0]], {width: 1000, height: 500});
  assert.deepEqual([calls.length, reframed], [2, [0, 1]]);
  assert.notEqual(framing.layout(), null);
});

function fakeCanvasPage({legacyMap = false} = {}) {
  const arcs = [];
  const elements = {};
  const element = tag => {
    const node = {tagName: tag.toUpperCase(), id: '', children: [], parentElement: null, clientWidth: 600, clientHeight: 400,
      append(...nodes) { nodes.forEach(child => { child.parentElement = this; this.children.push(child); }); },
      replaceChildren(...nodes) { this.children = []; this.append(...nodes); },
      replaceWith(other) { elements[other.id] = other; delete elements[this.id]; }};
    if (tag === 'canvas') {
      const context = {arcs, clearRect() {}, fillRect() {}, beginPath() {}, fill() {}, arc: (x, y, radius) => arcs.push([x, y, radius])};
      node.getContext = () => context;
    }
    return node;
  };
  globalThis.document = {createElement: element, getElementById: id => elements[id] || null};
  if (legacyMap) elements.map = Object.assign(element('canvas'), {id: 'map'});
  return {arcs, elements};
}

test('the graph container replaces the old map canvas, or is the one already there', () => {
  const {elements} = fakeCanvasPage({legacyMap: true});
  const container = graphContainer();
  assert.deepEqual([container.id, container.tagName, elements.map, elements.graph3d], ['graph3d', 'DIV', undefined, container]);
  assert.equal(graphContainer(), container);
});

test('without WebGL the graph is drawn flat on a canvas in the visible container, the current track larger', () => {
  const {arcs} = fakeCanvasPage();
  const container = graphContainer();
  drawCanvasFallback({nodes: [nodeAt('a', 72, 108, 0, {color: '#111'}), nodeAt('b', 252, 180, 0, {color: '#222'})]}, container, 'b');
  const [canvas] = container.children;
  assert.deepEqual([container.children.length, canvas.tagName, canvas.parentElement, canvas.id], [1, 'CANVAS', container, 'map']);
  assert.deepEqual(arcs, [[300 + 72, 200 - 108, 5], [300 + 252, 200 - 180, 9]]);
});

test('the graph is fitted to its element and reports the size it took', () => {
  const sizes = [];
  const graph = {width(value) { sizes.push(['width', value]); return this; }, height(value) { sizes.push(['height', value]); return this; }};
  assert.deepEqual(fitGraphToElement(graph, {clientWidth: 640, clientHeight: 480}), {width: 640, height: 480});
  assert.deepEqual(sizes, [['width', 640], ['height', 480]]);
});

test('a resize of the element, its panel or the window is reported', () => {
  const observed = [], listeners = [];
  let report;
  globalThis.ResizeObserver = class { constructor(callback) { report = callback; } observe(element) { observed.push(element); } };
  globalThis.window = {addEventListener: (type, listener) => listeners.push([type, listener])};
  const panel = {id: 'panel'}, element = {id: 'graph', parentElement: panel};
  let resized = 0;
  observeElementResize(element, () => { resized += 1; });
  assert.deepEqual(observed, [element, panel]);
  assert.deepEqual(listeners.map(([type]) => type), ['resize']);
  report(); listeners[0][1]();
  assert.equal(resized, 2);
});

test('without ResizeObserver or a window, nothing is observed', () => {
  observeElementResize({parentElement: null}, () => assert.fail('never called'));
});
