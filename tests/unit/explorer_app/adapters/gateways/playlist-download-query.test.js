// Issue #146: the M3U endpoint's query string for a playlist recipe.
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {playlistRecipe} from '../../../../../music_explorer/frameworks/explorer/assets/app/domain/playlist-recipe.js';
import {playlistDownloadQuery} from '../../../../../music_explorer/frameworks/explorer/assets/app/adapters/gateways/playlist-download-query.js';

const base = {startTrackId: 'track-start', bpmMin: '120', bpmMax: '128'};

test('the endpoint and its parameters in a stable order', () => {
  const cases = [
    [{}, 'start=track-start&bpm_min=120&bpm_max=128&count=10&min_key_strength=0.5'],
    [{durationMinutes: '45'}, 'start=track-start&bpm_min=120&bpm_max=128&duration_minutes=45&min_key_strength=0.5'],
    [{harmonicMixing: false}, 'start=track-start&bpm_min=120&bpm_max=128&count=10&harmonic=off'],
    [{energyArc: 'rise', energyLow: '0.2', energyHigh: '0.7', moodHold: 'relaxing'},
      'start=track-start&bpm_min=120&bpm_max=128&count=10&min_key_strength=0.5&arc=rise&energy_low=0.2&energy_high=0.7&mood=relaxing'],
    [{energyArc: 'fall', energyHigh: '0.7'}, 'start=track-start&bpm_min=120&bpm_max=128&count=10&min_key_strength=0.5&arc=fall&energy_high=0.7'],
  ];
  for (const [controls, query] of cases) {
    assert.equal(playlistDownloadQuery(playlistRecipe({...base, ...controls})), '/api/playlists/m3u?' + query);
  }
});

test('blank BPM bounds are sent blank, for the server to reject', () => {
  assert.equal(playlistDownloadQuery(playlistRecipe({startTrackId: 'a'})),
    '/api/playlists/m3u?start=a&bpm_min=&bpm_max=&count=10&min_key_strength=0.5');
});
