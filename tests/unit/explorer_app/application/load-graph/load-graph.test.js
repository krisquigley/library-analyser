// Issue #146: loading the library graph, choosing the tracked mood and filtering what it shows.
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {createGraphLoad} from '../../../../../music_explorer/frameworks/explorer/assets/app/application/load-graph/load-graph.js';
import {GRAPH_LOAD_EVENT_TYPES} from '../../../../../music_explorer/frameworks/explorer/assets/app/application/load-graph/graph-load-events.js';
import {EMPTY_GRAPH_CONTROLS} from '../../../../../music_explorer/frameworks/explorer/assets/app/domain/graph-filters.js';

const node = (id, bpm) => ({id, bpm, genres: [], genreThreshold: 0.1, genreThresholdApplies: false});
const MODEL = {nodes: [node('slow', 90), node('fast', 140)], links: [], unpositioned: [],
  availableMoods: ['relaxing', 'heavy'], selectedMood: 'relaxing', metadata: {}, genreOptions: []};

function memorySession(initial = {}) {
  let session = {loadState: 'idle', model: null, visible: null, controls: EMPTY_GRAPH_CONTROLS, ...initial};
  return {read: () => session, write: changes => { session = {...session, ...changes}; }};
}

function harness({loadMoodGraph, session = memorySession(), nextFrame = async () => {}} = {}) {
  const requests = [];
  const published = [];
  const graphLoad = createGraphLoad({
    explorerApi: {loadMoodGraph: loadMoodGraph || (async mood => { requests.push(mood); return {dto: mood}; })},
    graphSession: session,
    clock: {nextFrame},
    eventBus: {publish: event => published.push({...event, loadState: session.read().loadState}), subscribe() {}},
    buildGraphModel: () => MODEL,
  });
  const types = () => published.map(event => event.type);
  return {graphLoad, session, requests, published, types};
}

test('the event types are the ones the use case publishes', () => {
  assert.deepEqual(GRAPH_LOAD_EVENT_TYPES, ['graph-controls-edited', 'graph-load-started', 'graph-model-building', 'graph-model-built',
    'graph-render-due', 'graph-ready', 'graph-load-failed', 'graph-filters-applied']);
});

test('a load fetches the graph for the tracked mood, says when it builds the model, renders it and is ready', async () => {
  const {graphLoad, session, requests, published, types} = harness();
  await graphLoad.load();
  assert.deepEqual(requests, ['']);
  assert.deepEqual(types(), ['graph-load-started', 'graph-model-building', 'graph-model-built', 'graph-render-due', 'graph-ready']);
  assert.deepEqual(published.map(event => event.loadState), ['loading', 'loading', 'rendering', 'rendering', 'ready']);
  assert.equal(session.read().model, MODEL);
  assert.equal(session.read().controls.mood, 'relaxing', 'the graph own mood is tracked when none was asked for');
  assert.deepEqual(published[2].visible.nodes.map(n => n.id), ['slow', 'fast']);
});

test('the graph is rendered only after the next frame', async () => {
  let frame;
  const {graphLoad, types} = harness({nextFrame: () => new Promise(resolve => { frame = resolve; })});
  const loading = graphLoad.load();
  await new Promise(resolve => setImmediate(resolve));
  assert.deepEqual(types(), ['graph-load-started', 'graph-model-building', 'graph-model-built']);
  frame();
  await loading;
  assert.deepEqual(types().slice(3), ['graph-render-due', 'graph-ready']);
});

test('a failed load says why and passes the error on', async () => {
  const {graphLoad, session, published} = harness({loadMoodGraph: async () => { throw new Error('graph temporarily unavailable'); }});
  await assert.rejects(graphLoad.load(), /graph temporarily unavailable/);
  assert.deepEqual(published.at(-1), {type: 'graph-load-failed', message: 'graph temporarily unavailable', loadState: 'failed'});
  assert.equal(session.read().loadState, 'failed');
});

test('a newer load supersedes an older one, which then publishes nothing more', async () => {
  const answers = [];
  const {graphLoad, types} = harness({loadMoodGraph: () => new Promise(resolve => answers.push(resolve))});
  const older = graphLoad.load();
  const newer = graphLoad.load();
  answers[1]({});
  await newer;
  answers[0]({});
  await older;
  assert.deepEqual(types(), ['graph-load-started', 'graph-load-started', 'graph-model-building', 'graph-model-built',
    'graph-render-due', 'graph-ready']);
});

test('a superseded load that fails stays quiet', async () => {
  const answers = [];
  const {graphLoad, types} = harness({loadMoodGraph: () => new Promise((resolve, reject) => answers.push(reject))});
  const older = graphLoad.load();
  graphLoad.load();
  answers[0](new Error('late'));
  await older;
  assert.deepEqual(types(), ['graph-load-started', 'graph-load-started']);
});

test('choosing a mood before the graph is ready only records it', async () => {
  const {graphLoad, session, requests, types} = harness();
  await graphLoad.chooseMood('heavy');
  assert.deepEqual(requests, []);
  assert.equal(session.read().controls.mood, 'heavy');
  assert.deepEqual(types(), ['graph-controls-edited']);
  await graphLoad.load();
  assert.deepEqual(requests, ['heavy']);
});

test('choosing a mood once the graph is ready reloads it for that mood', async () => {
  const {graphLoad, requests} = harness();
  await graphLoad.load();
  await graphLoad.chooseMood('heavy');
  assert.deepEqual(requests, ['', 'heavy']);
});

test('filters apply to a ready graph without fetching it again', async () => {
  const {graphLoad, session, requests, published} = harness();
  await graphLoad.load();
  graphLoad.editControls({bpmMin: 100});
  assert.equal(graphLoad.applyFilters(), true);
  assert.deepEqual(requests, ['']);
  assert.deepEqual(session.read().visible.nodes.map(n => n.id), ['fast']);
  assert.deepEqual([published.at(-1).type, published.at(-1).shown], ['graph-filters-applied', true]);
});

test('filters wait while the graph is not ready', () => {
  const {graphLoad, session, published} = harness();
  graphLoad.editControls({bpmMin: 100});
  assert.equal(graphLoad.applyFilters(), false);
  assert.equal(session.read().visible, null);
  assert.deepEqual(published.at(-1), {type: 'graph-filters-applied', shown: false, model: null, visible: null, loadState: 'idle'});
});

test('clearing the filters keeps the mood and shows every track again', async () => {
  const {graphLoad, session} = harness();
  await graphLoad.load();
  graphLoad.editControls({bpmMin: 100, genres: ['jazz']});
  graphLoad.applyFilters();
  graphLoad.clearFilters();
  assert.deepEqual(session.read().controls, {mood: 'relaxing', bpmMin: null, bpmMax: null, genres: []});
  assert.deepEqual(session.read().visible.nodes.map(n => n.id), ['slow', 'fast']);
});

test('a use case refuses adapters that do not implement its ports', () => {
  assert.throws(() => createGraphLoad({explorerApi: {}, graphSession: memorySession(), clock: {nextFrame() {}},
    eventBus: {publish() {}, subscribe() {}}, buildGraphModel: () => MODEL}), /ExplorerApi needs loadMoodGraph/);
  assert.throws(() => createGraphLoad({explorerApi: {loadMoodGraph() {}}, graphSession: memorySession(), clock: {nextFrame() {}},
    eventBus: {publish() {}, subscribe() {}}}), /needs a graph model builder/);
});
