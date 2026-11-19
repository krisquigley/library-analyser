// Issue #146: which tracks the graph filters keep.
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {applyMoodGraphFilters, clearedGraphFilters, editGraphControls, EMPTY_GRAPH_CONTROLS, passesGraphFilters} from '../../../../music_explorer/frameworks/explorer/assets/app/domain/graph-filters.js';

const node = (id, bpm, genres = [], threshold = {}) => ({id, bpm, genres, genreThreshold: 0.1, genreThresholdApplies: false, ...threshold});

test('BPM bounds keep tracks inside them and drop tracks without a BPM', () => {
  const filters = {bpmMin: 100, bpmMax: 130};
  assert.deepEqual([node('a', 100), node('b', 130), node('c', 99), node('d', 131), node('e', null)]
    .map(n => passesGraphFilters(n, filters)), [true, true, false, false, false]);
  assert.equal(passesGraphFilters(node('e', null), {}), true);
});

test('genres keep a track that scores any of them above its threshold', () => {
  const filters = {genres: ['rock', 'jazz']};
  assert.equal(passesGraphFilters(node('a', 120, [['rock', 0.2]]), filters), true);
  assert.equal(passesGraphFilters(node('b', 120, [['rock', 0.1]]), filters), false);
  assert.equal(passesGraphFilters(node('c', 120, [['pop', 0.9]]), filters), false);
  assert.equal(passesGraphFilters(node('d', 120, [['rock', 0.2]], {genreThreshold: 0.3, genreThresholdApplies: true}), filters), false);
  assert.equal(passesGraphFilters(node('e', 120, [['rock', 0.2]], {genreThreshold: 0.3}), filters), true);
});

test('filtering keeps the links between kept tracks and every unpositioned track', () => {
  const model = {
    nodes: [node('a', 120), node('b', 90), node('c', 125)],
    links: [{source: 'a', target: 'c'}, {source: {id: 'a'}, target: {id: 'b'}}, {source: {id: 'c'}, target: 'a'}],
    unpositioned: [{track_id: 'u'}],
  };
  const visible = applyMoodGraphFilters(model, {bpmMin: 100});
  assert.deepEqual(visible.nodes.map(n => n.id), ['a', 'c']);
  assert.deepEqual(visible.links, [model.links[0], model.links[2]]);
  assert.equal(visible.unpositioned, model.unpositioned);
  assert.equal(applyMoodGraphFilters(model).nodes.length, 3);
});

test('new graph controls track no mood and filter nothing', () => {
  assert.deepEqual(EMPTY_GRAPH_CONTROLS, {mood: '', bpmMin: null, bpmMax: null, genres: []});
  assert.ok(Object.isFrozen(EMPTY_GRAPH_CONTROLS) && Object.isFrozen(EMPTY_GRAPH_CONTROLS.genres));
});

test('editing graph controls returns new controls with their own genre list', () => {
  const genres = ['rock'];
  const edited = editGraphControls(EMPTY_GRAPH_CONTROLS, {bpmMin: 90, genres});
  genres.push('jazz');
  assert.deepEqual(edited, {mood: '', bpmMin: 90, bpmMax: null, genres: ['rock']});
  assert.ok(Object.isFrozen(edited) && Object.isFrozen(edited.genres));
  assert.throws(() => editGraphControls(EMPTY_GRAPH_CONTROLS, {tempo: 1}), /Unknown graph control: tempo/);
});

test('clearing the filters keeps the tracked mood', () => {
  const controls = editGraphControls(EMPTY_GRAPH_CONTROLS, {mood: 'heavy', bpmMin: 90, bpmMax: 150, genres: ['jazz']});
  assert.deepEqual(clearedGraphFilters(controls), {mood: 'heavy', bpmMin: null, bpmMax: null, genres: []});
});
