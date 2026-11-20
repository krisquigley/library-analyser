// Issue #146: the M3U endpoint's query string for a playlist recipe.
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {playlistRecipe} from '../../../../../music_explorer/frameworks/explorer/assets/app/domain/playlist-recipe.js';
import {playlistDownloadQuery, playlistPreviewQuery} from '../../../../../music_explorer/frameworks/explorer/assets/app/adapters/gateways/playlist-download-query.js';

const base = {startTrackId: 'track-start', bpmMin: '120', bpmMax: '128'};
const arc = (shape, fields = {}) => ({shape, low: '', high: '', length: '', ...fields});

test('the endpoint and its parameters in a stable order', () => {
  const cases = [
    [{}, 'start=track-start&bpm_min=120&bpm_max=128&count=10&min_key_strength=0.5'],
    [{durationMinutes: '45'}, 'start=track-start&bpm_min=120&bpm_max=128&duration_minutes=45&min_key_strength=0.5'],
    [{harmonicMixing: false}, 'start=track-start&bpm_min=120&bpm_max=128&count=10&harmonic=off'],
    [{energyArcs: [arc('rise', {low: '0.2', high: '0.7'})], moodHold: 'relaxing'},
      'start=track-start&bpm_min=120&bpm_max=128&count=10&min_key_strength=0.5&arc=rise&energy_low=0.2&energy_high=0.7&mood=relaxing'],
    [{energyArcs: [arc('fall', {high: '0.7'})]}, 'start=track-start&bpm_min=120&bpm_max=128&count=10&min_key_strength=0.5&arc=fall&energy_high=0.7'],
  ];
  for (const [controls, query] of cases) {
    assert.equal(playlistDownloadQuery(playlistRecipe({...base, ...controls})), '/api/playlists/m3u?' + query);
  }
});

test('blank BPM bounds are sent blank, for the server to reject', () => {
  assert.equal(playlistDownloadQuery(playlistRecipe({startTrackId: 'a'})),
    '/api/playlists/m3u?start=a&bpm_min=&bpm_max=&count=10&min_key_strength=0.5');
});

test('a chain repeats each arc\'s parameters in order, a blank keeping an unset value\'s place', () => {
  const recipe = playlistRecipe({...base, count: '25', arcUnit: 'tracks',
    energyArcs: [arc('rise', {high: '0.8', length: '4'}), arc('steady', {low: '0.3', length: '3'}), arc('dip', {length: '5'})]});
  assert.equal(playlistDownloadQuery(recipe), '/api/playlists/m3u?start=track-start&bpm_min=120&bpm_max=128'
    + '&min_key_strength=0.5&arc=rise&arc=steady&arc=dip&energy_low=&energy_low=0.3&energy_low='
    + '&energy_high=0.8&energy_high=&energy_high=&arc_tracks=4&arc_tracks=3&arc_tracks=5');
});

test('arc lengths in minutes, and a missing one sent blank for the server to reject', () => {
  const recipe = playlistRecipe({...base, durationMinutes: '45', arcUnit: 'minutes',
    energyArcs: [arc('rise', {length: '20'}), arc('fall')]});
  assert.equal(playlistDownloadQuery(recipe), '/api/playlists/m3u?start=track-start&bpm_min=120&bpm_max=128'
    + '&min_key_strength=0.5&arc=rise&arc=fall&arc_minutes=20&arc_minutes=');
});

test('the preview asks the preview endpoint with the same parameters as the download (#138)', () => {
  const recipe = playlistRecipe({...base, energyArcs: [arc('peak', {length: '6'})], arcUnit: 'tracks'});
  assert.equal(playlistPreviewQuery(recipe),
    playlistDownloadQuery(recipe).replace('/api/playlists/m3u?', '/api/playlists/preview?'));
});
