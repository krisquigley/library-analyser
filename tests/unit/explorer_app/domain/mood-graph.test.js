// Issue #146: the mood-axis graph model the 3D scene and the filters work on.
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {libraryArousalRange, moodGraphModel, moodNodeColor, moodToTrack, trackBpmsOf} from '../../../../music_explorer/frameworks/explorer/assets/app/domain/mood-graph.js';
import {applyMoodGraphFilters, EMPTY_GRAPH_CONTROLS} from '../../../../music_explorer/frameworks/explorer/assets/app/domain/graph-filters.js';

const axis = (raw, normalized) => ({label: 'axis', raw, normalized});

function positioned(id, {valence, arousal, bpm = 120, genres = []}) {
  return {track_id: id, display_label: id.toUpperCase(), x: axis(valence, valence), y: axis(arousal, arousal),
    z: axis(0.5, 0.5), mood_score: null, bpm, genres, reasons: []};
}

const GRAPH = {
  positioned: [
    positioned('calm', {valence: 0.2, arousal: 0.1, genres: [['ambient', 0.6], ['rock', 0.05]]}),
    positioned('loud', {valence: 0.8, arousal: 0.9, genres: [['rock', 0.7], ['ambient', 0.3]]}),
  ],
  edges: [{a: 'calm', b: 'loud', score: 0.84, explanation: 'shared genre'}, {a: 'calm', b: 'gone', score: 0.5}],
  unpositioned: [{track_id: 'u', display_label: 'U', reasons: ['no mood']}],
  available_moods: ['happy'], selected_mood: 'happy', metadata: {graph_status: {state: 'ready'}},
};

test('a node is placed at its normalised axes on the scene scale', () => {
  const [calm] = moodGraphModel(GRAPH).nodes;
  assert.deepEqual([calm.id, calm.label, calm.name], ['calm', 'CALM', 'CALM']);
  assert.deepEqual([calm.x, calm.y, calm.z, calm.fx, calm.fy, calm.fz], [72, 36, 180, 72, 36, 180]);
  assert.deepEqual(calm.axis, {x: GRAPH.positioned[0].x, y: GRAPH.positioned[0].y, z: GRAPH.positioned[0].z});
});

test('node colours run from the calmest to the most energetic track in this library', () => {
  const [calm, loud] = moodGraphModel(GRAPH).nodes;
  assert.equal(calm.color, moodNodeColor(0, 0));
  assert.equal(loud.color, moodNodeColor(1, 1));
  assert.equal(moodNodeColor(0, 0), 'hsl(215 48% 27%)');
  assert.equal(moodNodeColor(1, 1), 'hsl(20 80% 60%)');
});

test('a library with one valence and arousal colours every node from the middle', () => {
  const model = moodGraphModel({...GRAPH, positioned: [GRAPH.positioned[0]]});
  assert.equal(model.nodes[0].color, moodNodeColor(0.5, 0.5));
  assert.deepEqual(model.colorRanges, {valence: [0.2, 0.2], arousal: [0.1, 0.1]});
});

test('links join only positioned tracks and are named for their relatedness', () => {
  const {links} = moodGraphModel(GRAPH);
  assert.equal(links.length, 1);
  assert.deepEqual([links[0].source, links[0].target, links[0].name], ['calm', 'loud', 'relatedness 0.8: shared genre']);
});

test('genre options are the genres some track scores above 0.1', () => {
  assert.deepEqual(moodGraphModel(GRAPH).genreOptions, ['ambient', 'rock']);
});

test('per-track genre thresholds apply only when the graph says so', () => {
  assert.equal(moodGraphModel(GRAPH).nodes[0].genreThresholdApplies, false);
  const indexed = moodGraphModel(GRAPH, {genreThresholdApplies: true});
  assert.deepEqual([indexed.nodes[0].genreThreshold, indexed.nodes[0].genreThresholdApplies], [0.1, true]);
});

test('the graph keeps its moods, metadata and unpositioned tracks', () => {
  const model = moodGraphModel(GRAPH);
  assert.deepEqual([model.availableMoods, model.selectedMood, model.metadata, model.unpositioned],
    [['happy'], 'happy', {graph_status: {state: 'ready'}}, GRAPH.unpositioned]);
  assert.deepEqual(moodGraphModel({}).nodes, []);
});

test('the tracked mood is the one asked for while the graph offers it, else the graph own', () => {
  const model = {availableMoods: ['relaxing', 'heavy'], selectedMood: 'relaxing'};
  assert.equal(moodToTrack('heavy', model), 'heavy');
  assert.equal(moodToTrack('happy', model), 'relaxing');
  assert.equal(moodToTrack('', model), 'relaxing');
  assert.equal(moodToTrack('heavy', {availableMoods: [], selectedMood: ''}), '');
});

test('a track carries its own genre threshold, and the default where it has none', () => {
  const indexed = moodGraphModel({...GRAPH, positioned: [{...GRAPH.positioned[0], genre_threshold: 0.4}, GRAPH.positioned[1]]},
    {genreThresholdApplies: true});
  assert.deepEqual(indexed.nodes.map(node => node.genreThreshold), [0.4, 0.1]);
});

test('a genre no track scores above 0.1 is not offered', () => {
  const model = moodGraphModel({...GRAPH, positioned: [positioned('quiet', {valence: 0.5, arousal: 0.5,
    genres: [['jazz', 0.1], ['folk', 0.05], ['ambient', 0.11]]})]});
  assert.deepEqual(model.genreOptions, ['ambient']);
});

test('tracking another mood leaves every node where it was', () => {
  const place = model => model.nodes.map(node => [node.id, node.x, node.y, node.z, node.fx, node.fy, node.fz]);
  assert.deepEqual(place(moodGraphModel({...GRAPH, selected_mood: 'sad', available_moods: ['happy', 'sad']})), place(moodGraphModel(GRAPH)));
});

test('a node keeps its colour when another mood is tracked, and when filters drop other tracks', () => {
  const model = moodGraphModel(GRAPH);
  const otherMood = moodGraphModel({...GRAPH, selected_mood: 'heavy',
    positioned: GRAPH.positioned.map(track => ({...track, z: {...track.z, raw: 0.9, normalized: 0.9, label: 'heavy'}}))});
  assert.deepEqual(otherMood.nodes.map(node => node.color), model.nodes.map(node => node.color));
  const faster = moodGraphModel({...GRAPH, positioned: [GRAPH.positioned[0], {...GRAPH.positioned[1], bpm: 140}]});
  const [, loud] = faster.nodes;
  const kept = applyMoodGraphFilters(faster, {...EMPTY_GRAPH_CONTROLS, bpmMin: 130});
  assert.deepEqual(kept.nodes.map(node => [node.id, node.color]), [[loud.id, loud.color]]);
});

test('the graph knows the BPM of each positioned track, for the library rows (#235)', () => {
  const bpms = trackBpmsOf({nodes: [{id: 'a', bpm: 120.4}, {id: 'b', bpm: null}]});
  assert.deepEqual([...bpms], [['a', 120.4], ['b', null]]);
  assert.deepEqual([...trackBpmsOf({nodes: []})], []);
});

test("the library's arousal range is the lowest and highest the graph places, as raw arousal (#265)", () => {
  assert.deepEqual(libraryArousalRange({colorRanges: {arousal: [3.12, 6.84]}}), {low: 3.12, high: 6.84});
  assert.equal(libraryArousalRange({colorRanges: {arousal: null}}), null);
});

test("#291: a node carries its track's key, or none", () => {
  const keyed = {...GRAPH, positioned: [{...GRAPH.positioned[0], key: 'A minor'}, GRAPH.positioned[1]]};
  assert.deepEqual(moodGraphModel(keyed).nodes.map(node => node.key), ['A minor', null]);
});
