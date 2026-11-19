// Issue #146: what the graph status panel and the graph controls show.
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {
  GRAPH_IDLE_STATUS, graphControlOptionsViewModel, graphControlValuesViewModel, graphStatusMessage, presentGraphLoadEvent,
} from '../../../../../music_explorer/frameworks/explorer/assets/app/adapters/presenters/graph-load-presenter.js';

const BUILD = 'Run music-analyzer graph build --database DB, then reload this read-only explorer.';
const visible = {nodes: [{}, {}]};
const modelWith = graphStatus => ({metadata: graphStatus ? {graph_status: graphStatus} : {}});

test('before loading, the panel says the graph starts on its own', () => {
  assert.deepEqual(GRAPH_IDLE_STATUS, {status: 'idle',
    message: 'The library graph starts automatically; search and track detail remain usable.'});
});

test('each load event has its status', () => {
  assert.deepEqual(presentGraphLoadEvent({type: 'graph-load-started'}),
    {status: 'loading', message: 'Loading graph. The track list, search, history, and detail remain usable.'});
  assert.deepEqual(presentGraphLoadEvent({type: 'graph-model-built', visible}),
    {status: 'rendering', message: 'Rendering 2 positioned tracks'});
  assert.deepEqual(presentGraphLoadEvent({type: 'graph-ready', model: modelWith({state: 'ready'}), visible}),
    {status: 'ready', message: 'Graph ready: 2 positioned tracks'});
  assert.deepEqual(presentGraphLoadEvent({type: 'graph-load-failed', message: 'graph temporarily unavailable'}),
    {status: 'error', message: 'Graph failed: graph temporarily unavailable'});
  assert.deepEqual(presentGraphLoadEvent({type: 'graph-filters-applied', shown: true, model: modelWith({state: 'ready'}), visible}),
    {status: 'ready', message: 'Graph ready: 2 positioned tracks'});
  assert.equal(presentGraphLoadEvent({type: 'graph-filters-applied', shown: false}), null);
  assert.equal(presentGraphLoadEvent({type: 'graph-render-due', visible}), null);
});

test('a stored graph that is not ready says so and how to rebuild it, without the API reason or action', () => {
  const unsafe = {reason: '/Users/alice/private.sqlite', action: 'run hidden command'};
  assert.equal(graphStatusMessage({state: 'stale', ...unsafe}, 3),
    `Graph stale: showing the last stored snapshot for 3 positioned tracks. ${BUILD}`);
  assert.equal(graphStatusMessage({state: 'build_needed', ...unsafe}, 3),
    `Graph needs a build: no current stored graph snapshot is available. ${BUILD}`);
  assert.equal(graphStatusMessage({state: 'failed', ...unsafe}, 3),
    `Graph failed: the last stored graph build did not complete successfully. ${BUILD}`);
  assert.equal(graphStatusMessage({state: 'building', ...unsafe}, 3),
    `Graph building: a stored graph snapshot is not ready yet. ${BUILD}`);
  assert.equal(graphStatusMessage({state: 'mystery'}, 3),
    `Graph status unavailable: showing 3 positioned tracks from the stored snapshot. ${BUILD}`);
  assert.equal(graphStatusMessage(undefined, 3), 'Graph ready: 3 positioned tracks');
});

test('the controls offer the graph moods and genres, marking the chosen ones', () => {
  const model = {availableMoods: ['relaxing', 'heavy'], genreOptions: ['jazz', 'rock']};
  const controls = {mood: 'heavy', bpmMin: 90, bpmMax: null, genres: ['rock']};
  assert.deepEqual(graphControlOptionsViewModel(model, controls), {
    moodChoices: [{value: 'relaxing', label: 'relaxing', selected: false}, {value: 'heavy', label: 'heavy', selected: true}],
    genreChoices: [{value: 'jazz', label: 'jazz', selected: false}, {value: 'rock', label: 'rock', selected: true}],
  });
  assert.deepEqual(graphControlOptionsViewModel({availableMoods: [], genreOptions: []}, controls).moodChoices,
    [{value: '', label: 'No supported moods', selected: false}]);
  assert.deepEqual(graphControlValuesViewModel(controls), {bpmMin: '90', bpmMax: '', genres: ['rock']});
});
