// Issue #146 (#86): drawing the graph on demand. A still view stops redrawing; a moved view, input,
// new data or a resize draws again.
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {createGraphRendering} from '../../../../../music_explorer/frameworks/explorer/assets/app/application/render-graph/render-graph.js';
import {GRAPH_RENDERING_EVENT_TYPES} from '../../../../../music_explorer/frameworks/explorer/assets/app/application/render-graph/render-graph-events.js';

function harness({canPause = true} = {}) {
  const loop = [];
  const published = [];
  const rendering = createGraphRendering({
    renderer: {pause: () => loop.push('pause'), resume: () => loop.push('resume'), canPause: () => canPause},
    eventBus: {publish: event => published.push(event), subscribe() {}},
  });
  let now = 0;
  // One page frame: the view is observed, and a drawn frame is reported while drawing.
  const frame = (pose = 'still', ms = 16) => {
    now += ms;
    rendering.viewObserved(pose);
    if (rendering.drawing()) rendering.frameDrawn(now);
  };
  const idle = (pose = 'still') => { for (let t = 0; t < 2000; t += 16) frame(pose); };
  return {rendering, loop, published, types: () => published.map(event => event.type), frame, idle};
}

test('the event types are the ones the use case publishes', () => {
  assert.deepEqual(GRAPH_RENDERING_EVENT_TYPES, ['graph-rendering-paused', 'graph-rendering-resumed']);
});

test('a still view stops redrawing once, after half a second of quiet', () => {
  const {rendering, loop, types, frame} = harness();
  frame();
  for (let t = 0; t < 480; t += 16) frame();
  assert.deepEqual(loop, []);
  frame();
  frame();
  assert.deepEqual(loop, ['pause']);
  assert.equal(rendering.drawing(), false);
  assert.deepEqual(types(), ['graph-rendering-paused']);
});

test('a moved view draws again at once, inside the frame, and settles again once still', () => {
  const {rendering, loop, types, frame, idle} = harness();
  idle();
  frame('moved');
  assert.deepEqual(loop, ['pause', 'resume']);
  assert.equal(rendering.drawing(), true);
  idle('moved');
  assert.deepEqual(loop, ['pause', 'resume', 'pause']);
  assert.deepEqual(types(), ['graph-rendering-paused', 'graph-rendering-resumed', 'graph-rendering-paused']);
});

test('a view that keeps moving, like a camera focus, keeps drawing until it stops', () => {
  const {rendering, loop, frame, idle} = harness();
  for (let t = 0; t < 700; t += 16) frame(`focus ${t}`);
  assert.deepEqual([loop, rendering.drawing()], [[], true]);
  idle('settled');
  assert.deepEqual(loop, ['pause']);
});

test('a wake outside a frame draws at the next frame, not inside the handler that woke it', () => {
  const {rendering, loop, types, frame, idle} = harness();
  idle();
  rendering.wake();
  assert.deepEqual([loop, rendering.drawing(), types().at(-1)], [['pause'], true, 'graph-rendering-resumed']);
  frame();
  assert.deepEqual(loop, ['pause', 'resume']);
  frame();
  assert.deepEqual(loop, ['pause', 'resume'], 'resumed once');
});

test('a wake followed by a moved view draws once', () => {
  const {rendering, loop, frame, idle} = harness();
  idle();
  rendering.wake();
  frame('moved');
  assert.deepEqual(loop, ['pause', 'resume']);
});

test('a wake while drawing only restarts the quiet period', () => {
  const {rendering, loop, published, frame} = harness();
  frame();
  for (let t = 0; t < 400; t += 16) frame();
  rendering.wake();
  for (let t = 0; t < 400; t += 16) frame();
  assert.deepEqual([loop, published], [[], []]);
});

test('a graph that cannot pause keeps drawing', () => {
  const {rendering, loop, idle} = harness({canPause: false});
  idle();
  assert.deepEqual([loop, rendering.drawing()], [[], true]);
});

test('the use case refuses adapters that do not implement its ports', () => {
  assert.throws(() => createGraphRendering({renderer: {pause() {}}, eventBus: {publish() {}, subscribe() {}}}),
    /GraphRenderer needs resume/);
});
