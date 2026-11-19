// Issue #146: the playlist recipe the Download M3U controls describe.
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {playlistRecipe} from '../../../../music_explorer/frameworks/explorer/assets/app/domain/playlist-recipe.js';

const controls = {startTrackId: 'track-1', bpmMin: '120', bpmMax: '128'};

test('a track-count playlist with the defaults', () => {
  assert.deepEqual(playlistRecipe(controls), {
    startTrackId: 'track-1', bpmMin: '120', bpmMax: '128', length: {count: '10'},
    harmonicMixing: true, minimumKeyStrength: '0.5', energyArc: null, moodHold: null,
  });
});

test('a start track is required', () => {
  for (const startTrackId of [undefined, null, '']) {
    assert.throws(() => playlistRecipe({...controls, startTrackId}), /Select a start track before downloading M3U/);
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

test('an energy arc with the ends of its range that are set', () => {
  assert.deepEqual(playlistRecipe({...controls, energyArc: 'rise', energyHigh: ' 0.7 '}).energyArc,
    {shape: 'rise', low: null, high: '0.7'});
  assert.deepEqual(playlistRecipe({...controls, energyArc: 'peak', energyLow: '0.2', energyHigh: '0.9'}).energyArc,
    {shape: 'peak', low: '0.2', high: '0.9'});
});

test('no arc means no range', () => {
  for (const energyArc of [undefined, '', 'none']) {
    assert.equal(playlistRecipe({...controls, energyArc, energyLow: '0.2'}).energyArc, null);
  }
});

test('a mood hold', () => {
  assert.equal(playlistRecipe({...controls, moodHold: 'relaxing'}).moodHold, 'relaxing');
  assert.equal(playlistRecipe({...controls, moodHold: ''}).moodHold, null);
});

test('a recipe cannot be changed once made', () => {
  const recipe = playlistRecipe({...controls, energyArc: 'rise'});

  assert.ok(Object.isFrozen(recipe) && Object.isFrozen(recipe.length) && Object.isFrozen(recipe.energyArc));
});
