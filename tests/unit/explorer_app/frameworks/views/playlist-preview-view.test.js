// Issue #138: the playlist preview on screen.
import {test, beforeEach} from 'node:test';
import assert from 'node:assert/strict';
import {playlistPreviewView} from '../../../../../music_explorer/frameworks/explorer/assets/app/frameworks/views/playlist-preview-view.js';
import {descendants, fakeElement, installFakeDocument} from '../fake-document.js';

let drawn;
beforeEach(() => {
  installFakeDocument([]);
  drawn = [];
  const createElement = globalThis.document.createElement;
  globalThis.document.createElement = tag => {
    const made = createElement(tag);
    if (tag === 'canvas') made.getContext = () => recordingContext(drawn);
    return made;
  };
});

function recordingContext(log) {
  const record = name => (...args) => log.push([name, ...args]);
  return {clearRect: record('clear'), beginPath: record('begin'), moveTo: record('move'), lineTo: record('line'),
    stroke: record('stroke'), setLineDash: record('dash'),
    set strokeStyle(value) { log.push(['color', value]); }, set lineWidth(value) { log.push(['width', value]); }};
}

const CHART = Object.freeze({width: 300, height: 80, padding: 8, level: [[[8, 72], [292, 8]]], target: [[[8, 40]], [[150, 8], [292, 8]]],
  label: 'Energy across 2 tracks'});

const ROW = Object.freeze({place: '1', track: 'Synthetic – Opening', length: '4:00', bpm: '120.0', key: '8A', energy: '0.3', target: '0.2',
  transition: 'Start'});

function mounted() {
  const requests = [];
  const view = playlistPreviewView({onPreviewRequested: () => requests.push('preview')});
  const panel = fakeElement('section');
  view.mount(panel, {previewDisabled: false, status: {text: '', urgent: false}, rows: [],
    chart: {...CHART, level: [], target: [], label: 'No energy to chart yet.'}});
  const byId = id => descendants(panel).find(node => node.id === id);
  const cells = () => byId('playlist-preview-tracks').children.map(row => row.children.map(cell => cell.textContent));
  return {view, requests, byId, cells};
}

test('mounting draws the Preview button and an empty list, and asks for nothing until clicked', () => {
  const {requests, byId, cells} = mounted();
  const button = byId('preview-playlist');
  assert.deepEqual([button.type, button.textContent, button.disabled], ['button', 'Preview', false]);
  assert.deepEqual([requests, cells()], [[], []]);
  button.onclick();
  assert.deepEqual(requests, ['preview']);
});

test('the list has a heading for each column', () => {
  const {byId} = mounted();
  const heading = byId('playlist-preview-heading');
  assert.deepEqual(heading.children.map(cell => cell.textContent), ['#', 'Track', 'Length', 'BPM', 'Key', 'Energy', 'Target', 'Transition']);
});

test('showing a preview draws its rows, and a later update replaces them', () => {
  const {view, cells} = mounted();
  view.show({previewDisabled: false, status: {text: '1 track.', urgent: false}, rows: [ROW]});
  assert.deepEqual(cells(), [['1', 'Synthetic – Opening', '4:00', '120.0', '8A', '0.3', '0.2', 'Start']]);
  view.show({previewDisabled: false, status: {text: 'Preview failed: no', urgent: true}, rows: []});
  assert.deepEqual(cells(), []);
});

test('an update without rows keeps the list, and the status and button follow the update', () => {
  const {view, byId, cells} = mounted();
  view.show({rows: [ROW]});
  view.show({previewDisabled: true, status: {text: 'Previewing the playlist…', urgent: false}});
  assert.equal(cells().length, 1);
  assert.equal(byId('preview-playlist').disabled, true);
  const status = byId('playlist-preview-status');
  assert.deepEqual([status.textContent, status.getAttribute('role')], ['Previewing the playlist…', 'status']);
  view.show({previewDisabled: false, status: {text: 'Preview failed: no', urgent: true}});
  assert.deepEqual([status.getAttribute('role'), status.getAttribute('aria-live')], ['alert', 'assertive']);
});

test('showing before mounting does nothing', () => {
  assert.doesNotThrow(() => playlistPreviewView({onPreviewRequested() {}}).show({rows: [ROW]}));
});

test('the energy chart is drawn on a labelled canvas: the target dashed, the reached energy solid', () => {
  const {view, byId} = mounted();
  drawn.length = 0;
  view.show({chart: CHART});
  const canvas = byId('playlist-energy-chart');
  assert.deepEqual([canvas.width, canvas.height, canvas.getAttribute('role'), canvas.getAttribute('aria-label')],
    [300, 80, 'img', 'Energy across 2 tracks']);
  const moves = drawn.filter(([name]) => name === 'move' || name === 'line').map(step => step.join(' '));
  assert.deepEqual(moves, ['move 8 40', 'move 150 8', 'line 292 8', 'move 8 72', 'line 292 8']);
  const dashes = drawn.filter(([name]) => name === 'dash').map(([, pattern]) => pattern);
  assert.deepEqual(dashes, [[4, 3], []]);
  assert.equal(drawn[0][0], 'clear');
});

test('Preview stays disabled with its reason until the recipe is ready, and while a preview runs (#234)', () => {
  const {view, byId} = mounted();
  const button = byId('preview-playlist');
  view.show({readiness: {ready: false, reason: 'To preview: enter a minimum BPM.'}});
  assert.equal(button.disabled, true);
  assert.equal(byId('playlist-preview-reason').textContent, 'To preview: enter a minimum BPM.');
  assert.equal(button.getAttribute('aria-describedby'), 'playlist-preview-reason');
  view.show({previewDisabled: false});
  assert.equal(button.disabled, true, 'a finished preview does not enable an incomplete recipe');
  view.show({readiness: {ready: true, reason: ''}});
  assert.deepEqual([button.disabled, byId('playlist-preview-reason').textContent], [false, '']);
  view.show({previewDisabled: true});
  assert.equal(button.disabled, true, 'busy while previewing');
});
