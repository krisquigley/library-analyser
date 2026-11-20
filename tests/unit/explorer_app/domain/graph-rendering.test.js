// Issue #146 (#86): the graph is drawn while its view can change, and pauses once it has been quiet.
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {
  GRAPH_RENDER_IDLE_MS, GRAPH_RENDERING_STATES, GraphRenderingTransitionError, nextGraphRenderingState, quietLongEnough,
} from '../../../../music_explorer/frameworks/explorer/assets/app/domain/graph-rendering.js';

test('the graph is drawing or paused; it pauses only while drawing, and anything can wake it', () => {
  assert.deepEqual(GRAPH_RENDERING_STATES, ['drawing', 'paused']);
  assert.deepEqual([nextGraphRenderingState('drawing', 'pause'), nextGraphRenderingState('paused', 'wake'),
    nextGraphRenderingState('drawing', 'wake')], ['paused', 'drawing', 'drawing']);
  assert.throws(() => nextGraphRenderingState('paused', 'pause'), GraphRenderingTransitionError);
  assert.throws(() => nextGraphRenderingState('asleep', 'wake'), /cannot wake while asleep/);
});

test('a view is quiet enough to pause after half a second without change', () => {
  assert.equal(GRAPH_RENDER_IDLE_MS, 500);
  assert.deepEqual([quietLongEnough(null, 9000), quietLongEnough(1000, 1499), quietLongEnough(1000, 1500)], [false, false, true]);
});
