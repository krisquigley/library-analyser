// Issue #146: the playlist recipe the Download M3U controls describe.
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {playlistRecipe} from '../../../../music_explorer/frameworks/explorer/assets/app/domain/playlist-recipe.js';

const controls = {startTrackId: 'track-1', bpmMin: '120', bpmMax: '128'};

test('a track-count playlist with the defaults', () => {
  assert.deepEqual(playlistRecipe(controls), {
    startTrackId: 'track-1', bpmMin: '120', bpmMax: '128', length: {count: '10'},
    harmonicMixing: true, minimumKeyStrength: '0.5', energyPlan: [], moodHold: null,
  });
});

test('a start track is required', () => {
  for (const startTrackId of [undefined, null, '']) {
    assert.throws(() => playlistRecipe({...controls, startTrackId}), /Select a start track first/);
  }
});

test('a duration replaces the track count', () => {
  assert.deepEqual(playlistRecipe({...controls, count: '25', durationMinutes: ' 45 '}).length, {durationMinutes: '45'});
  assert.deepEqual(playlistRecipe({...controls, count: '25', durationMinutes: '  '}).length, {count: '25'});
});

test('harmonic mixing off drops the minimum key strength', () => {
  const recipe = playlistRecipe({...controls, harmonicMixing: false, minimumKeyStrength: '0.8'});

  assert.equal(recipe.harmonicMixing, false);
  assert.equal(recipe.minimumKeyStrength, null);
  assert.equal(playlistRecipe({...controls, minimumKeyStrength: ' 0.7 '}).minimumKeyStrength, '0.7');
  assert.equal(playlistRecipe({...controls, minimumKeyStrength: ''}).minimumKeyStrength, '0.5');
});

const arc = (shape, fields = {}) => ({shape, low: '', high: '', length: '', ...fields});

test('an energy plan keeps each arc\'s shape, the ends of its range that are set, and its length', () => {
  const recipe = playlistRecipe({...controls, energyArcs: [arc('rise', {high: ' 0.7 '}), arc('dip', {low: '0.2', length: ' 4 '})],
    arcUnit: 'tracks'});
  assert.deepEqual(recipe.energyPlan, [{shape: 'rise', low: null, high: '0.7', length: null},
    {shape: 'dip', low: '0.2', high: null, length: '4'}]);
});

test('arcs with lengths set the playlist\'s length, in their unit', () => {
  const chain = [arc('rise', {length: '3'}), arc('fall', {length: '5'})];
  assert.deepEqual(playlistRecipe({...controls, count: '25', energyArcs: chain, arcUnit: 'tracks'}).length, {arcs: 'tracks'});
  assert.deepEqual(playlistRecipe({...controls, durationMinutes: '45', energyArcs: chain, arcUnit: 'minutes'}).length,
    {arcs: 'minutes'});
  assert.deepEqual(playlistRecipe({...controls, count: '25', energyArcs: [arc('rise')], arcUnit: 'tracks'}).length,
    {count: '25'}, 'an arc without a length spans the playlist');
});

test('no arcs, no plan', () => {
  for (const energyArcs of [undefined, []]) assert.deepEqual(playlistRecipe({...controls, energyArcs}).energyPlan, []);
});

test('a mood hold', () => {
  assert.equal(playlistRecipe({...controls, moodHold: 'relaxing'}).moodHold, 'relaxing');
  assert.equal(playlistRecipe({...controls, moodHold: ''}).moodHold, null);
});

test('a recipe cannot be changed once made', () => {
  const recipe = playlistRecipe({...controls, energyArcs: [arc('rise')]});

  assert.ok(Object.isFrozen(recipe) && Object.isFrozen(recipe.length) && Object.isFrozen(recipe.energyPlan)
    && Object.isFrozen(recipe.energyPlan[0]));
});
