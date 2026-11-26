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
  return {ok, text: async () => body, json: async () => JSON.parse(body), headers: {get: name => lowered[name.toLowerCase()] ?? null}};
}

function gatewayAnswering(answer) {
  const requests = [];
  const api = fetchExplorerApi(async (path, options) => { requests.push(options ? [path, options] : path); return answer; });
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

test('a track search asks for a page of 100 by title, from a cursor when given', async () => {
  const body = {tracks: [{handle: 'a'}], metadata: {track_count: 5}, next_cursor: 'c2'};
  const {api, requests} = gatewayAnswering({ok: true, json: async () => body, text: async () => JSON.stringify(body)});
  assert.deepEqual(await api.searchTracks({query: 'alpha beta', cursor: null}),
    {tracks: [{handle: 'a'}], metadata: {track_count: 5}, nextCursor: 'c2'});
  await api.searchTracks({query: 'alpha', cursor: 'c2'});
  assert.deepEqual(requests, ['/api/tracks/summary?limit=100&order=title&query=alpha+beta',
    '/api/tracks/summary?limit=100&order=title&query=alpha&cursor=c2']);
});

test('a track page without metadata or a cursor is the last page', async () => {
  const {api} = gatewayAnswering({ok: true, json: async () => ({}), text: async () => '{}'});
  assert.deepEqual(await api.searchTracks({query: 'a', cursor: null}), {tracks: [], metadata: {}, nextCursor: null});
});

test('a refused track search fails with the server message, not its JSON (#155)', async () => {
  const {api} = gatewayAnswering(response({ok: false, body: '{"error": "Explorer request failed"}',
    headers: {'Content-Type': 'application/json'}}));
  await assert.rejects(api.searchTracks({query: 'a', cursor: null}), {message: 'Explorer request failed'});
  const empty = gatewayAnswering(response({ok: false, body: ''}));
  await assert.rejects(empty.api.searchTracks({query: 'a', cursor: null}), {message: 'Track search failed'});
});

const REFUSAL = response({ok: false, body: '{"error": "Unknown track"}', headers: {'Content-Type': 'application/json'}});

test('choosing the current track posts the selection with its ticket and returns the new state', async () => {
  const {api, requests} = gatewayAnswering(response({body: '{"current_track_id": "t1", "selection_epoch": 4}'}));
  const state = await api.chooseCurrentTrack({trackId: 't1', selectionToken: 7, selectionEpoch: 3, clientId: 'tab-1'});
  assert.deepEqual(state, {current_track_id: 't1', selection_epoch: 4});
  assert.deepEqual(requests, [['/api/current', {method: 'POST', headers: {'Content-Type': 'application/json'},
    body: '{"track_id":"t1","selection_token":7,"selection_epoch":3,"selection_client_id":"tab-1"}'}]]);
});

test('undo and reset post to their own endpoint, and nothing else is a history action', async () => {
  const {api, requests} = gatewayAnswering(response({body: '{"current_track_id": null}'}));
  assert.deepEqual(await api.applyHistory('undo'), {current_track_id: null});
  await api.applyHistory('reset');
  assert.deepEqual(requests, [['/api/undo', {method: 'POST'}], ['/api/reset', {method: 'POST'}]]);
  await assert.rejects(api.applyHistory('tracks'), /not a history action: tracks/);
});

test('a track detail and the library state are read by GET', async () => {
  const {api, requests} = gatewayAnswering(response({body: '{"fields": {}}'}));
  assert.deepEqual(await api.loadTrackDetail('a/b c'), {fields: {}});
  await api.loadLibraryState();
  assert.deepEqual(requests, ['/api/tracks/a%2Fb%20c', '/api/state']);
});

test('refused selection, history, detail and state requests fail with the server message, not its JSON (#158)', async () => {
  const {api} = gatewayAnswering(REFUSAL);
  for (const request of [() => api.chooseCurrentTrack({trackId: 'x', selectionToken: 1, selectionEpoch: 0, clientId: 'c'}),
    () => api.applyHistory('undo'), () => api.loadTrackDetail('x'), () => api.loadLibraryState()]) {
    await assert.rejects(request(), {message: 'Unknown track'});
  }
  const plain = gatewayAnswering(response({ok: false, body: ''}));
  await assert.rejects(plain.api.loadTrackDetail('x'), {message: 'Track detail request failed'});
});

const PREVIEW_BODY = {
  tracks: [
    {track_id: 'a', title: 'Opening', artist: 'Synthetic', bpm: 120, key: 'A minor', camelot: '8A', arousal: 0.4,
      energy_target: 0.2, duration_seconds: 241.5},
    {track_id: 'b', title: 'Lift', artist: 'Synthetic', bpm: 122.5, key: null, camelot: null, arousal: null,
      energy_target: 0.6, duration_seconds: null},
  ],
  transitions: [{from_track_id: 'a', to_track_id: 'b', key_compatible: null, bpm_step_smooth: true, bpm_change: 2.5}],
  complete: false, warning: 'Only 2 of 10 tracks fit',
};

test('a playlist preview asks the preview endpoint and reads the walk the server took (#138)', async () => {
  const {api, requests} = gatewayAnswering(response({body: JSON.stringify(PREVIEW_BODY),
    headers: {'content-type': 'application/json'}}));
  const preview = await api.previewPlaylist(RECIPE);
  assert.ok(requests[0].startsWith('/api/playlists/preview?start='));
  assert.deepEqual(preview, {
    tracks: [
      {trackId: 'a', title: 'Opening', artist: 'Synthetic', bpm: 120, key: 'A minor', camelot: '8A', arousal: 0.4,
        energyTarget: 0.2, durationSeconds: 241.5},
      {trackId: 'b', title: 'Lift', artist: 'Synthetic', bpm: 122.5, key: null, camelot: null, arousal: null,
        energyTarget: 0.6, durationSeconds: null},
    ],
    transitions: [{fromTrackId: 'a', toTrackId: 'b', keyCompatible: null, bpmStepSmooth: true, bpmChange: 2.5}],
    complete: false, warning: 'Only 2 of 10 tracks fit',
  });
});

test('a preview the server shaped wrongly is refused whole, never half-read (#138)', async () => {
  const track = PREVIEW_BODY.tracks[0];
  const cases = [
    [{...PREVIEW_BODY, tracks: 'none'}, 'Invalid playlist preview: tracks must be a list'],
    [{...PREVIEW_BODY, tracks: [{...track, bpm: '120'}]}, 'Invalid playlist preview: track 1 bpm must be a number'],
    [{...PREVIEW_BODY, tracks: [{...track, title: null}]}, 'Invalid playlist preview: track 1 title must be text'],
    [{...PREVIEW_BODY, tracks: [{...track, energy_target: 'high'}]},
      'Invalid playlist preview: track 1 energy_target must be a number or null'],
    [{...PREVIEW_BODY, tracks: [{...track, duration_seconds: '4:01'}]},
      'Invalid playlist preview: track 1 duration_seconds must be a number or null'],
    [{...PREVIEW_BODY, transitions: [{...PREVIEW_BODY.transitions[0], key_compatible: 'yes'}]},
      'Invalid playlist preview: transition 1 key_compatible must be true, false or null'],
    [{...PREVIEW_BODY, complete: 'no'}, 'Invalid playlist preview: complete must be true or false'],
    [{...PREVIEW_BODY, warning: 3}, 'Invalid playlist preview: warning must be text or null'],
  ];
  for (const [body, message] of cases) {
    const {api} = gatewayAnswering(response({body: JSON.stringify(body), headers: {'content-type': 'application/json'}}));
    await assert.rejects(api.previewPlaylist(RECIPE), {message});
  }
});

test('a refused preview fails with the server message, not its JSON', async () => {
  const {api} = gatewayAnswering(response({ok: false, body: '{"error":"bpm bounds must be ordered"}',
    headers: {'content-type': 'application/json'}}));
  await assert.rejects(api.previewPlaylist(RECIPE), {message: 'bpm bounds must be ordered'});
});

test('saved recipes are listed by name, with when each was saved and what stops it loading (#139)', async () => {
  const {api, requests} = gatewayAnswering(response({headers: {'content-type': 'application/json'}, body: JSON.stringify({recipes: [
    {name: 'Warm-up', updated_at: '2026-11-20T10:00:00Z', problem: null},
    {name: 'Old', updated_at: '2026-11-01T10:00:00Z', problem: 'Its start track t is not an available track'}]})}));
  assert.deepEqual(await api.listSavedPlaylistRecipes(), [
    {name: 'Warm-up', updatedAt: '2026-11-20T10:00:00Z', problem: null},
    {name: 'Old', updatedAt: '2026-11-01T10:00:00Z', problem: 'Its start track t is not an available track'}]);
  assert.deepEqual(requests, ['/api/playlist-recipes']);
});

test('a saved recipe is loaded by name, and a list or recipe shaped wrongly is refused whole (#139)', async () => {
  const recipe = {format: 'playlist-recipe', version: 2};
  const loading = gatewayAnswering(response({headers: {'content-type': 'application/json'},
    body: JSON.stringify({name: 'Warm up & go', recipe})}));
  assert.deepEqual(await loading.api.loadSavedPlaylistRecipe('Warm up & go'), {name: 'Warm up & go', recipe});
  assert.deepEqual(loading.requests, ['/api/playlist-recipes/load?name=Warm+up+%26+go']);
  const cases = [
    ['listSavedPlaylistRecipes', {recipes: 'none'}, 'Invalid saved recipe list: recipes must be a list'],
    ['listSavedPlaylistRecipes', {recipes: [{name: 3, updated_at: 'x', problem: null}]}, 'Invalid saved recipe list: recipe 1 name must be text'],
    ['listSavedPlaylistRecipes', {recipes: [{name: 'a', updated_at: 'x', problem: 4}]}, 'Invalid saved recipe list: recipe 1 problem must be text or null'],
    ['loadSavedPlaylistRecipe', {name: 'a', recipe: []}, 'Invalid saved recipe: recipe must be a JSON object'],
  ];
  for (const [operation, body, message] of cases) {
    const {api} = gatewayAnswering(response({headers: {'content-type': 'application/json'}, body: JSON.stringify(body)}));
    await assert.rejects(api[operation]('a'), {message});
  }
});

test('a recipe that cannot be loaded fails with the server message (#139)', async () => {
  const {api} = gatewayAnswering(response({ok: false, headers: {'content-type': 'application/json'},
    body: '{"error":"No saved recipe named \\"a\\""}'}));
  await assert.rejects(api.loadSavedPlaylistRecipe('a'), {message: 'No saved recipe named "a"'});
});

test('a tag write is previewed with GET and applied with a JSON POST of its token (#132)', async () => {
  const previewBody = {token: 'tok', changes: [{file: 'one.mp3', field: 'bpm', current: null, proposed: '124', replaces: false}],
    skipped: [{track_id: 'sha256:b', reason: 'Nothing to change'}]};
  const preview = gatewayAnswering(response({body: JSON.stringify(previewBody), headers: {'Content-Type': 'application/json'}}));
  assert.deepEqual(await preview.api.previewTagWrite({trackIds: ['sha256:a', 'sha256:b'], policy: 'replace-existing'}),
    {token: 'tok', changes: previewBody.changes, skipped: [{trackId: 'sha256:b', reason: 'Nothing to change'}]});
  assert.deepEqual(preview.requests, ['/api/tag-write/preview?track=sha256%3Aa&track=sha256%3Ab&policy=replace-existing']);
  const reportBody = {outcomes: [{file: 'one.mp3', status: 'written', detail: 'BPM 124'}], notice: 'Rescan them.'};
  const apply = gatewayAnswering(response({body: JSON.stringify(reportBody), headers: {'Content-Type': 'application/json'}}));
  assert.deepEqual(await apply.api.applyTagWrite('tok'), reportBody);
  assert.deepEqual(apply.requests, [['/api/tag-write/apply', {method: 'POST', headers: {'Content-Type': 'application/json'},
    body: '{"token":"tok"}'}]]);
});

test('a tag write answer shaped wrongly is refused whole, and a refusal is told (#132)', async () => {
  for (const [operation, body, message] of [
    ['previewTagWrite', {token: 3, changes: [], skipped: []}, 'Invalid tag preview: token must be text or null'],
    ['previewTagWrite', {token: null, changes: [{file: 'a', field: 'mood', current: null, proposed: 'x', replaces: false}], skipped: []},
      'Invalid tag preview: change 1 field must be bpm or key'],
    ['previewTagWrite', {token: null, changes: [], skipped: [{track_id: 'a'}]}, 'Invalid tag preview: skipped track 1 reason must be text'],
    ['applyTagWrite', {outcomes: [{file: 'a', status: 'done', detail: ''}], notice: ''},
      'Invalid tag write report: outcome 1 status must be written, skipped or failed'],
  ]) {
    const {api} = gatewayAnswering(response({body: JSON.stringify(body), headers: {'Content-Type': 'application/json'}}));
    await assert.rejects(api[operation]({trackIds: ['a'], policy: 'fill-empty'}), {message});
  }
  const {api} = gatewayAnswering(response({ok: false, headers: {'Content-Type': 'application/json'},
    body: '{"error":"This approval has already been used: preview again"}'}));
  await assert.rejects(api.applyTagWrite('tok'), {message: 'This approval has already been used: preview again'});
});

test('labels for the named tracks are asked for by ID and checked (#243)', async () => {
  const body = {labels: [{track_id: 'sha256:a', title: 'Alpha', artist: 'Synthetic'}]};
  const labelled = gatewayAnswering(response({body: JSON.stringify(body), headers: {'Content-Type': 'application/json'}}));
  assert.deepEqual(await labelled.api.labelTracks(['sha256:a', 'sha256:b']), [{trackId: 'sha256:a', title: 'Alpha', artist: 'Synthetic'}]);
  assert.deepEqual(labelled.requests, ['/api/track-labels?track=sha256%3Aa&track=sha256%3Ab']);
  const wrong = gatewayAnswering(response({body: JSON.stringify({labels: [{}]}), headers: {'Content-Type': 'application/json'}}));
  await assert.rejects(wrong.api.labelTracks(['a']), /Invalid track labels: label 1 track_id must be text/);
});

test('a hand-built playlist downloads with a JSON POST of its tracks in order, and a refusal says why (#278)', async () => {
  const {api, requests} = gatewayAnswering(response({body: '#EXTM3U\n/b.flac\n/a.flac\n', headers: {
    'Content-Disposition': 'attachment; filename="hand-built-playlist.m3u"', 'Content-Type': 'audio/x-mpegurl; charset=utf-8'}}));
  assert.deepEqual(await api.downloadHandBuiltPlaylist(['b', 'a']), {filename: 'hand-built-playlist.m3u',
    contents: '#EXTM3U\n/b.flac\n/a.flac\n', contentType: 'audio/x-mpegurl; charset=utf-8'});
  assert.deepEqual(requests, [['/api/playlists/hand-built', {method: 'POST', headers: {'Content-Type': 'application/json'},
    body: '{"track_ids":["b","a"]}'}]]);
  const bare = gatewayAnswering(response({body: '#EXTM3U\n'}));
  assert.deepEqual(await bare.api.downloadHandBuiltPlaylist(['a']),
    {filename: 'hand-built-playlist.m3u', contents: '#EXTM3U\n', contentType: 'audio/x-mpegurl;charset=utf-8'});
  for (const [answer, message] of [
    [response({ok: false, body: '{"error": "Add at least one track to the playlist"}', headers: {'Content-Type': 'application/json'}}),
      'Add at least one track to the playlist'],
    [response({ok: false, body: ''}), 'M3U download failed']]) {
    await assert.rejects(gatewayAnswering(answer).api.downloadHandBuiltPlaylist(['a']), {message});
  }
});
