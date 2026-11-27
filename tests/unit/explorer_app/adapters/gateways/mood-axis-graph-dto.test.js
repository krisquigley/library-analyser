// Issue #146: the graph response's compact and indexed DTOs, checked and normalised at the boundary.
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {isIndexedMoodAxisGraph, normalizeMoodAxisGraphDto} from '../../../../../music_explorer/frameworks/explorer/assets/app/adapters/gateways/mood-axis-graph-dto.js';

const EMPTY = {positioned: [], edges: [], unpositioned: [], available_moods: [], selected_mood: '', metadata: {}};

test('no graph is an empty graph, and an unversioned graph is already normal', () => {
  assert.deepEqual(normalizeMoodAxisGraphDto(null), EMPTY);
  const unversioned = {positioned: [], edges: []};
  assert.equal(normalizeMoodAxisGraphDto(unversioned), unversioned);
});

test('an unknown DTO version is refused', () => {
  assert.throws(() => normalizeMoodAxisGraphDto({dto_version: 'mood-axis-graph-v9'}),
    /Unsupported mood-axis graph DTO version: mood-axis-graph-v9/);
});

test('a compact graph names its nodes, links and unpositioned tracks', () => {
  const graph = normalizeMoodAxisGraphDto({dto_version: 'mood-axis-graph-compact-v1', selected_mood: 'happy',
    available_moods: ['happy'], metadata: {m: 1},
    nodes: [{id: 't1', label: 'One', axis: {x: 1, y: 2, z: 3}, bpm: 120, genre_threshold: 0.2}],
    links: [{source: 't1', target: 't2', score: 0.5, supportedGroupCount: 2}],
    unpositioned: [{id: 'u1'}]});
  assert.deepEqual(graph.positioned, [{track_id: 't1', display_label: 'One', x: 1, y: 2, z: 3, mood_score: null,
    bpm: 120, genres: [], reasons: [], genre_threshold: 0.2}]);
  assert.deepEqual(graph.edges, [{a: 't1', b: 't2', score: 0.5, explanation: undefined, provenance: undefined,
    supported_group_count: 2}]);
  assert.deepEqual(graph.unpositioned, [{track_id: 'u1', display_label: 'u1', reasons: []}]);
  assert.deepEqual([graph.selected_mood, graph.available_moods, graph.metadata], ['happy', ['happy'], {m: 1}]);
});

const INDEXED = {
  dto_version: 'mood-axis-graph-indexed-v1', selected_mood: 'happy',
  axis: [{key: 'x', label: 'valence', scale: 's'}, {key: 'y', label: 'arousal', scale: 's'}, {key: 'z', label: 'mood', scale: 's'}],
  genre_labels: ['rock'], reason_text: ['no mood'], explanation_table: ['near'], provenance_table: ['p'],
  link_defaults: {explanation: 0, provenance: 0}, key_table: ['A minor'],
  nodes: [['t1', 'One', 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 120, 0.7, [[0, 0.8]], [0], 0.25, 0],
    ['t2', 'Two', 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, null, null, [], []]],
  links: [[0, 1, 0.9, 3]],
  unpositioned: [['u1', 'U', [0]]],
};

test('an indexed graph resolves its rows through its tables', () => {
  assert.equal(isIndexedMoodAxisGraph(INDEXED), true);
  assert.equal(isIndexedMoodAxisGraph({dto_version: 'mood-axis-graph-compact-v1'}), false);
  const graph = normalizeMoodAxisGraphDto(INDEXED);
  const [one, two] = graph.positioned;
  assert.deepEqual(one.x, {label: 'valence', raw: 0.1, normalized: 0.2, scale: 's'});
  assert.deepEqual([one.bpm, one.genres, one.reasons, one.genre_threshold], [120, [['rock', 0.8]], ['no mood'], 0.25]);
  assert.deepEqual(one.mood_score, {label: 'happy', raw: 0.7, normalized: 0.7, scale: 'sigmoid_mean_score_0_1'});
  assert.deepEqual([two.bpm, two.mood_score], [0.5, null]);
  assert.deepEqual([one.key, two.key], ['A minor', null], '#291: the key comes through its table');
  assert.deepEqual(graph.edges, [{a: 't1', b: 't2', score: 0.9, explanation: 'near', provenance: 'p', supported_group_count: 3}]);
  assert.deepEqual(graph.unpositioned, [{track_id: 'u1', display_label: 'U', reasons: ['no mood']}]);
});

test('a malformed indexed graph is refused, not half-read', () => {
  const cases = [
    [{nodes: [['t1', 'One']]}, /Invalid indexed graph node row at 0/],
    [{nodes: [['t1', 'One', 0, 0, 0, 0, 0, 0, 1, 1, [[5, 0.8]], []]]}, /Invalid indexed graph genre reference: 5/],
    [{links: [[0, 7, 0.9]]}, /Invalid indexed graph link endpoint at 0/],
    [{key_table: []}, /Invalid indexed graph key reference: 0/],
    [{links: [[0, 1]]}, /Invalid indexed graph link row at 0/],
    [{unpositioned: [['u1']]}, /Invalid indexed graph unpositioned row at 0/],
  ];
  for (const [change, message] of cases) {
    assert.throws(() => normalizeMoodAxisGraphDto({...INDEXED, ...change}), message);
  }
});
