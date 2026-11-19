// Issue #146: the ExplorerApi port over fetch.
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {fetchExplorerApi} from '../../../../../music_explorer/frameworks/explorer/assets/app/adapters/gateways/explorer-api-gateway.js';
import {EXPLORER_API} from '../../../../../music_explorer/frameworks/explorer/assets/app/application/ports/explorer-api.js';
import {requirePort} from '../../../../../music_explorer/frameworks/explorer/assets/app/application/ports/port.js';
import {playlistRecipe} from '../../../../../music_explorer/frameworks/explorer/assets/app/domain/playlist-recipe.js';

const RECIPE = playlistRecipe({startTrackId: 'track-start', bpmMin: '120', bpmMax: '128'});

function response({ok = true, body = '', headers = {}}) {
  const lowered = Object.fromEntries(Object.entries(headers).map(([name, value]) => [name.toLowerCase(), value]));
  return {ok, text: async () => body, headers: {get: name => lowered[name.toLowerCase()] ?? null}};
}

function gatewayAnswering(answer) {
  const requests = [];
  const api = fetchExplorerApi(async path => { requests.push(path); return answer; });
  return {api, requests};
}

test('the gateway implements the ExplorerApi port', () => {
  const {api} = gatewayAnswering(response({}));
  assert.equal(requirePort(EXPLORER_API, api), api);
});

test('a playlist download asks for the recipe and returns the file the server named', async () => {
  const {api, requests} = gatewayAnswering(response({body: '#EXTM3U\n/song.mp3\n', headers: {
    'Content-Disposition': 'attachment; filename="journey.m3u"', 'Content-Type': 'audio/x-mpegurl',
    'X-Music-Explorer-Playlist-Warning': 'dead end after 3 tracks'}}));
  assert.deepEqual(await api.downloadPlaylist(RECIPE), {
    filename: 'journey.m3u', contents: '#EXTM3U\n/song.mp3\n', contentType: 'audio/x-mpegurl',
    warning: 'dead end after 3 tracks'});
  assert.deepEqual(requests, ['/api/playlists/m3u?start=track-start&bpm_min=120&bpm_max=128&count=10&min_key_strength=0.5']);
});

test('a response without headers gets the default name and type', async () => {
  const {api} = gatewayAnswering({ok: true, text: async () => '#EXTM3U\n'});
  assert.deepEqual(await api.downloadPlaylist(RECIPE), {
    filename: 'library-graph-playlist.m3u', contents: '#EXTM3U\n', contentType: 'audio/x-mpegurl;charset=utf-8',
    warning: ''});
});

test('a refused download fails with the server message, not its JSON (#149)', async () => {
  const {api} = gatewayAnswering(response({ok: false, body: '{"error": "bpm bounds must be ordered"}',
    headers: {'Content-Type': 'application/json'}}));
  await assert.rejects(api.downloadPlaylist(RECIPE), {message: 'bpm bounds must be ordered'});
});

test('a refused download with a plain, empty or unreadable body still says why', async () => {
  const cases = [
    [response({ok: false, body: 'playlist temporarily unavailable'}), 'playlist temporarily unavailable'],
    [response({ok: false, body: ''}), 'M3U download failed'],
    [response({ok: false, body: '{not json', headers: {'Content-Type': 'application/json'}}), '{not json'],
    [response({ok: false, body: '{"detail": "x"}', headers: {'Content-Type': 'application/json'}}), '{"detail": "x"}'],
  ];
  for (const [answer, message] of cases) {
    const {api} = gatewayAnswering(answer);
    await assert.rejects(api.downloadPlaylist(RECIPE), {message});
  }
});

test('the mood graph is asked for with the indexed contract, and for the tracked mood when there is one', async () => {
  const graph = {dto_version: 'mood-axis-graph-indexed-v1'};
  const {api, requests} = gatewayAnswering({ok: true, json: async () => graph, text: async () => JSON.stringify(graph)});
  assert.equal(await api.loadMoodGraph(''), graph);
  await api.loadMoodGraph('heavy & calm');
  assert.deepEqual(requests, ['/api/mood-axis-graph?contract=v3', '/api/mood-axis-graph?mood=heavy+%26+calm&contract=v3']);
});

test('a refused graph fails with the server message, not its JSON (#152)', async () => {
  const cases = [
    [response({ok: false, body: '{"error": "Explorer request failed"}', headers: {'Content-Type': 'application/json'}}), 'Explorer request failed'],
    [response({ok: false, body: 'graph temporarily unavailable'}), 'graph temporarily unavailable'],
    [response({ok: false, body: ''}), 'Graph request failed'],
  ];
  for (const [answer, message] of cases) {
    const {api} = gatewayAnswering(answer);
    await assert.rejects(api.loadMoodGraph(''), {message});
  }
});
