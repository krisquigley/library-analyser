// Issue #139: the drafted playlist as a version 1 recipe file, for `music-analyzer playlist-recipe save`.
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {
  PlaylistRecipeDocumentError, playlistRecipeDocument,
} from '../../../../music_explorer/frameworks/explorer/assets/app/domain/playlist-recipe-document.js';
import {EMPTY_PLAYLIST_DRAFT} from '../../../../music_explorer/frameworks/explorer/assets/app/domain/playlist-draft.js';

const draft = (changes = {}) => ({...EMPTY_PLAYLIST_DRAFT, bpmMin: '120', bpmMax: ' 128.5 ', ...changes});
const arc = (shape, fields = {}) => ({shape, length: '', low: '', high: '', ...fields});

test('a plain draft becomes a recipe with numbers, its track count and harmonic mixing', () => {
  assert.deepEqual(playlistRecipeDocument(draft(), 'track-1'), {
    format: 'playlist-recipe', version: 1, start_track_id: 'track-1', bpm: {min: 120, max: 128.5},
    length: {tracks: 10}, harmonic_mixing: {enabled: true, minimum_key_strength: 0.5}, energy_plan: [], mood_hold: null,
  });
});

test('a duration replaces the track count, and a single arc without a length spans the playlist', () => {
  const document = playlistRecipeDocument(draft({durationMinutes: '45', harmonicMixing: false, minimumKeyStrength: '0.7',
    energyArcs: [arc('rise', {high: '0.8'})], moodHold: 'relaxed'}), 'track-1');
  assert.deepEqual([document.length, document.harmonic_mixing, document.energy_plan, document.mood_hold], [
    {minutes: 45}, {enabled: false, minimum_key_strength: 0.7},
    [{shape: 'rise', energy_low: null, energy_high: 0.8}], 'relaxed']);
});

test('arcs with lengths set the length, each in the draft unit, and the recipe has none of its own', () => {
  const tracks = playlistRecipeDocument(draft({energyArcs: [arc('rise', {length: '6'}), arc('dip', {length: '4', low: '0.1'})]}), 't');
  assert.equal('length' in tracks, false);
  assert.deepEqual(tracks.energy_plan, [{shape: 'rise', tracks: 6, energy_low: null, energy_high: null},
    {shape: 'dip', tracks: 4, energy_low: 0.1, energy_high: null}]);
  const minutes = playlistRecipeDocument(draft({arcLengthUnit: 'minutes', energyArcs: [arc('peak', {length: '12.5'})]}), 't');
  assert.deepEqual(minutes.energy_plan, [{shape: 'peak', minutes: 12.5, energy_low: null, energy_high: null}]);
});

test('a draft that cannot be a recipe says why', () => {
  const cases = [
    [draft(), null, 'Select a start track first'],
    [draft({bpmMin: ''}), 't', 'Min BPM must be a number'],
    [draft({bpmMax: 'fast'}), 't', 'Max BPM must be a number'],
    [draft({count: '2.5'}), 't', 'Track count must be a whole number'],
    [draft({durationMinutes: 'long'}), 't', 'Duration must be a number'],
    [draft({minimumKeyStrength: 'x'}), 't', 'Min key strength must be a number'],
    [draft({energyArcs: [arc('rise'), arc('fall')]}), 't', 'Each arc in a chain needs a length'],
    [draft({energyArcs: [arc('rise', {length: '4'}), arc('fall')]}), 't', 'Each arc in a chain needs a length'],
    [draft({energyArcs: [arc('rise', {length: '4.5'})]}), 't', 'Arc 1 length must be a whole number of tracks'],
    [draft({energyArcs: [arc('rise', {high: 'top'})]}), 't', 'Arc 1 high energy must be a number'],
  ];
  for (const [given, start, message] of cases) {
    assert.throws(() => playlistRecipeDocument(given, start), error => error instanceof PlaylistRecipeDocumentError
      && error.message === message, message);
  }
});
