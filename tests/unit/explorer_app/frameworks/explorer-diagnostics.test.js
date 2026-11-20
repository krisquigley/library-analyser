// Issue #146 (owner decision A): the opt-in diagnostics seam the timing tools and composition tests observe.
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {
  createExplorerDiagnostics, diagnosticsRequested, installExplorerDiagnostics,
} from '../../../../music_explorer/frameworks/explorer/assets/app/frameworks/explorer-diagnostics.js';
import {createInMemoryEventBus} from '../../../../music_explorer/frameworks/explorer/assets/app/frameworks/in-memory-event-bus.js';

function seam(overrides = {}) {
  const camera = createInMemoryEventBus();
  const selection = createInMemoryEventBus();
  let state = {currentTrackId: 'a', history: ['b']};
  const sceneObjects = {renderer: {name: 'renderer'}};
  const viewFunctions = {detailField: () => 'field'};
  const diagnostics = createExplorerDiagnostics({
    buses: [[['camera-focus-started', 'camera-focus-finished'], camera], [['track-chosen'], selection]],
    snapshot: () => state, scene: () => sceneObjects, views: () => viewFunctions, ...overrides});
  return {diagnostics, camera, selection, setState: next => { state = next; }, sceneObjects, viewFunctions};
}

test('the seam is off unless the page address asks for diagnostics', () => {
  assert.equal(diagnosticsRequested(''), false);
  assert.equal(diagnosticsRequested('?track=a'), false);
  assert.equal(diagnosticsRequested('?diagnostics'), true);
  assert.equal(diagnosticsRequested('?track=a&diagnostics=1'), true);
});

test('a subscriber hears the events of the bus that carries that type, until it unsubscribes', () => {
  const {diagnostics, camera, selection} = seam();
  const heard = [];
  const stop = diagnostics.subscribe('camera-focus-started', event => heard.push(event));
  diagnostics.subscribe('track-chosen', event => heard.push(event));
  camera.publish({type: 'camera-focus-started', focusGeneration: 1});
  selection.publish({type: 'track-chosen', trackId: 'b'});
  stop();
  camera.publish({type: 'camera-focus-started', focusGeneration: 2});
  assert.deepEqual(heard, [{type: 'camera-focus-started', focusGeneration: 1}, {type: 'track-chosen', trackId: 'b'}]);
  assert.deepEqual(diagnostics.eventTypes(), ['camera-focus-started', 'camera-focus-finished', 'track-chosen']);
});

test("a dispatch is observed just before and after the page's own handlers, for timing", () => {
  const {diagnostics, camera} = seam();
  const heard = [];
  camera.subscribe('camera-focus-started', () => heard.push('page'));
  const stop = diagnostics.observe('camera-focus-started', {before: () => heard.push('before'), after: () => heard.push('after')});
  camera.publish({type: 'camera-focus-started', focusGeneration: 1});
  stop();
  camera.publish({type: 'camera-focus-started', focusGeneration: 2});
  assert.deepEqual(heard, ['before', 'page', 'after', 'page']);
});

test('an event type no bus carries is refused, and two buses cannot claim one type', () => {
  assert.throws(() => seam().diagnostics.subscribe('graph-ready', () => {}), /No diagnostics event: graph-ready/);
  assert.throws(() => seam().diagnostics.observe('graph-ready', {}), /No diagnostics event: graph-ready/);
  const bus = createInMemoryEventBus();
  assert.throws(() => createExplorerDiagnostics({buses: [[['a'], bus], [['a'], bus]], snapshot: () => ({}), scene: () => ({}),
    views: () => ({})}),
    /Two buses carry the event a/);
});

test('a snapshot is a frozen copy of the state now: changing it changes nothing, and it does not follow the page', () => {
  const {diagnostics, setState} = seam();
  const first = diagnostics.snapshot();
  assert.deepEqual(first, {currentTrackId: 'a', history: ['b']});
  assert.ok(Object.isFrozen(first) && Object.isFrozen(first.history));
  assert.throws(() => { first.history.push('c'); }, TypeError);
  setState({currentTrackId: 'c', history: []});
  assert.deepEqual([first.currentTrackId, diagnostics.snapshot().currentTrackId], ['a', 'c']);
});

test('the scene is handed over live, for the timing tools to measure, and the views that draw detached elements', () => {
  const {diagnostics, sceneObjects, viewFunctions} = seam();
  assert.equal(diagnostics.scene(), sceneObjects);
  assert.equal(diagnostics.views(), viewFunctions);
  assert.ok(Object.isFrozen(diagnostics));
});

test('installing puts a read-only seam on the page only when it is asked for', () => {
  const options = {buses: [], snapshot: () => ({}), scene: () => ({}), views: () => ({})};
  const page = {};
  assert.equal(installExplorerDiagnostics(page, '', options), null);
  assert.equal('explorerDiagnostics' in page, false);

  const installed = installExplorerDiagnostics(page, '?diagnostics', options);
  assert.equal(page.explorerDiagnostics, installed);
  assert.throws(() => { 'use strict'; page.explorerDiagnostics = {}; }, TypeError);
  assert.equal(Object.keys(page).includes('explorerDiagnostics'), false);
});
