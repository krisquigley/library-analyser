// Issue #146: the lifecycle of loading the library graph, as a state machine.
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {GRAPH_LOAD_STATES, GraphLoadTransitionError, nextGraphLoadState} from '../../../../music_explorer/frameworks/explorer/assets/app/domain/graph-load.js';

test('a load goes from loading through rendering to ready', () => {
  assert.deepEqual(GRAPH_LOAD_STATES, ['idle', 'loading', 'rendering', 'ready', 'failed']);
  assert.equal(nextGraphLoadState('idle', 'start'), 'loading');
  assert.equal(nextGraphLoadState('loading', 'build'), 'rendering');
  assert.equal(nextGraphLoadState('rendering', 'render'), 'ready');
});

test('loading or rendering can fail', () => {
  assert.equal(nextGraphLoadState('loading', 'fail'), 'failed');
  assert.equal(nextGraphLoadState('rendering', 'fail'), 'failed');
});

test('a reload, a retry or a newer load starts again', () => {
  for (const state of ['loading', 'rendering', 'ready', 'failed']) assert.equal(nextGraphLoadState(state, 'start'), 'loading');
});

test('illegal transitions are rejected', () => {
  const illegal = [['idle', 'build'], ['idle', 'fail'], ['loading', 'render'], ['ready', 'build'], ['ready', 'fail'],
    ['failed', 'render'], ['unknown', 'start']];
  for (const [state, action] of illegal) {
    assert.throws(() => nextGraphLoadState(state, action),
      error => error instanceof GraphLoadTransitionError && error.message === `A graph load cannot ${action} while ${state}`);
  }
});
