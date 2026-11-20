// Issue #146: drafting a playlist and downloading it as an M3U file.
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {createPlaylistDownload} from '../../../../../music_explorer/frameworks/explorer/assets/app/application/download-playlist/download-playlist.js';
import {
  PLAYLIST_DOWNLOAD_EVENT_TYPES,
} from '../../../../../music_explorer/frameworks/explorer/assets/app/application/download-playlist/playlist-download-events.js';

function recordingBus() {
  const published = [];
  return {published, publish: event => published.push(event), subscribe() {}};
}

function harness({downloadPlaylist, save = () => {}} = {}) {
  const requests = [];
  const saved = [];
  const eventBus = recordingBus();
  const explorerApi = {downloadPlaylist: downloadPlaylist || (async recipe => {
    requests.push(recipe);
    return {filename: 'journey.m3u', contents: '#EXTM3U\n', contentType: 'audio/x-mpegurl', warning: ''};
  })};
  const playlistFile = {save: file => { save(file); saved.push(file); }};
  const playlistDownload = createPlaylistDownload({explorerApi, playlistFile, eventBus});
  return {playlistDownload, requests, saved, published: eventBus.published};
}

test('the event types are the ones the use case publishes', () => {
  assert.deepEqual(PLAYLIST_DOWNLOAD_EVENT_TYPES,
    ['playlist-draft-edited', 'playlist-download-started', 'playlist-downloaded', 'playlist-download-failed']);
});

test('editing the draft publishes the edited draft', () => {
  const {playlistDownload, published} = harness();
  playlistDownload.edit({count: '25'});
  assert.equal(playlistDownload.draft().count, '25');
  assert.deepEqual(published, [{type: 'playlist-draft-edited', draft: playlistDownload.draft()}]);
});

test('each arc command edits the draft chain and publishes the edited draft', () => {
  const {playlistDownload, published} = harness();
  playlistDownload.addArc();
  playlistDownload.addArc();
  playlistDownload.editArc(1, {shape: 'fall', length: '8'});
  playlistDownload.moveArc(1, -1);
  playlistDownload.removeArc(1);
  assert.deepEqual(playlistDownload.draft().energyArcs, [{shape: 'fall', length: '8', low: '', high: ''}]);
  assert.equal(published.length, 5);
  assert.ok(published.every(event => event.type === 'playlist-draft-edited'));
  assert.equal(published.at(-1).draft, playlistDownload.draft());
});

test('a refused arc command changes nothing and publishes nothing', () => {
  const {playlistDownload, published} = harness();
  assert.throws(() => playlistDownload.removeArc(0), /no arc at place 0/);
  assert.deepEqual([playlistDownload.draft().energyArcs, published], [[], []]);
});

test('the download sends the arc chain in the draft unit', async () => {
  const {playlistDownload, requests} = harness();
  playlistDownload.edit({arcLengthUnit: 'minutes'});
  playlistDownload.addArc();
  playlistDownload.editArc(0, {length: '30'});
  await playlistDownload.download('track-start');
  assert.deepEqual([requests[0].length, requests[0].energyPlan[0].length], [{arcs: 'minutes'}, '30']);
});

test('a download requests the drafted recipe, saves the file and says so', async () => {
  const {playlistDownload, requests, saved, published} = harness();
  playlistDownload.edit({bpmMin: '120', bpmMax: '128'});
  await playlistDownload.download('track-start');
  assert.deepEqual(requests.map(recipe => [recipe.startTrackId, recipe.bpmMin, recipe.bpmMax]),
    [['track-start', '120', '128']]);
  assert.deepEqual(saved, [{filename: 'journey.m3u', contents: '#EXTM3U\n', contentType: 'audio/x-mpegurl', warning: ''}]);
  assert.deepEqual(published.slice(1), [
    {type: 'playlist-download-started'},
    {type: 'playlist-downloaded', filename: 'journey.m3u', warning: ''},
  ]);
});

test('a download passes on the server warning', async () => {
  const {playlistDownload, published} = harness({downloadPlaylist: async () =>
    ({filename: 'a.m3u', contents: '', contentType: 'audio/x-mpegurl', warning: 'dead end after 3 tracks'})});
  await playlistDownload.download('track-start');
  assert.deepEqual(published.at(-1), {type: 'playlist-downloaded', filename: 'a.m3u', warning: 'dead end after 3 tracks'});
});

test('without a start track the download fails without a request', async () => {
  const {playlistDownload, requests, published} = harness();
  await playlistDownload.download(null);
  assert.deepEqual(requests, []);
  assert.deepEqual(published, [
    {type: 'playlist-download-started'},
    {type: 'playlist-download-failed', message: 'Select a start track before downloading M3U'},
  ]);
});

test('a refused request or a failed save fails the download with its message', async () => {
  const refused = harness({downloadPlaylist: async () => { throw new Error('bpm bounds must be ordered'); }});
  await refused.playlistDownload.download('track-start');
  assert.deepEqual(refused.published.at(-1), {type: 'playlist-download-failed', message: 'bpm bounds must be ordered'});

  const unsaved = harness({save: () => { throw new Error('click blocked'); }});
  await unsaved.playlistDownload.download('track-start');
  assert.deepEqual(unsaved.published.at(-1), {type: 'playlist-download-failed', message: 'click blocked'});
});

test('a second download cannot start while one is in flight, and can after it ends', async () => {
  const playlist = {filename: 'a.m3u', contents: '', contentType: 'audio/x-mpegurl', warning: ''};
  let finish;
  const {playlistDownload, published} = harness({downloadPlaylist: () => new Promise(resolve => { finish = resolve; })});
  const first = playlistDownload.download('track-start');
  await assert.rejects(playlistDownload.download('track-start'), /cannot start while downloading/);
  finish(playlist);
  await first;
  const second = playlistDownload.download('track-start');
  finish(playlist);
  await second;
  assert.equal(published.filter(event => event.type === 'playlist-download-started').length, 2);
});

test('a use case refuses adapters that do not implement its ports', () => {
  assert.throws(() => createPlaylistDownload({explorerApi: {}, playlistFile: {save() {}}, eventBus: recordingBus()}),
    /ExplorerApi needs downloadPlaylist/);
});
