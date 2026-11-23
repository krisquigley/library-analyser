// Issue #146: the page's one 3D graph, the axes it shows and its frame loop, kept by the scene, not by page variables.
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {createForceGraphStage} from '../../../../../music_explorer/frameworks/explorer/assets/app/frameworks/graph-scene/force-graph-stage.js';

test('there is no graph until one is staged, and it is created and set up only once', () => {
  const created = [];
  const setUp = [];
  const stage = createForceGraphStage({create: element => { const graph = {element}; created.push(graph); return graph; }});
  assert.equal(stage.current(), null);
  const first = stage.ensure('viewport', graph => setUp.push(graph));
  assert.equal(stage.ensure('viewport', graph => setUp.push(graph)), first);
  assert.deepEqual([created, setUp, stage.current()], [[first], [first], first]);
  assert.equal(stage.shows(first), true);
  assert.equal(stage.shows({}), false);
});

test('the axes to show are the ones last staged', () => {
  const stage = createForceGraphStage({create: () => ({})});
  assert.deepEqual(stage.axisSpec(), []);
  const spec = [{key: 'x'}];
  stage.stageAxes(spec);
  assert.equal(stage.axisSpec(), spec);
});

test('the frame loop starts once', () => {
  const requested = [];
  const stage = createForceGraphStage({create: () => ({})});
  const onFrame = () => {};
  stage.startFrames(callback => requested.push(callback), onFrame);
  stage.startFrames(callback => requested.push(callback), onFrame);
  assert.deepEqual(requested, [onFrame]);
});
