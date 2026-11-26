// Issue #278: building a playlist by hand from the graph's labels, kept in this browser, and downloading it as an M3U.
// Issue #287: each change is previewed, as a recipe's playlist is, so the strip can show it as a table.
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {createHandBuiltPlaylist} from '../../../../../music_explorer/frameworks/explorer/assets/app/application/build-playlist/build-playlist.js';
import {HAND_BUILT_PLAYLIST_EVENT_TYPES} from '../../../../../music_explorer/frameworks/explorer/assets/app/application/build-playlist/hand-built-playlist-events.js';

const previewTrack = trackId => ({trackId, title: 'Track ' + trackId, artist: 'Synthetic', bpm: 120, key: null, camelot: null,
  arousal: null, energyTarget: null, durationSeconds: 200});

// The server's answer: the playable tracks ('gone' is not), each step between them.
function answerFor(trackIds) {
  const tracks = trackIds.filter(trackId => trackId !== 'gone').map(previewTrack);
  const transitions = tracks.slice(1).map((track, place) => ({fromTrackId: tracks[place].trackId, toTrackId: track.trackId,
    keyCompatible: null, bpmStepSmooth: true, bpmChange: 0}));
  return {tracks, transitions, complete: tracks.length === trackIds.length, warning: null};
}

function harness({kept = null, keepFails = false, readFails = false, held = false} = {}) {
  const published = [], saved = [], files = [], asked = [], downloads = [], waiting = [];
  const store = {
    load() { if (readFails) throw new Error('blocked'); return kept; },
    save(trackIds) { if (keepFails) throw new Error('quota'); saved.push(trackIds); },
  };
  const explorerApi = {
    previewHandBuiltPlaylist: trackIds => {
      asked.push(trackIds);
      if (trackIds.includes('broken')) return Promise.reject(new Error('Playlist preview failed'));
      if (!held) return Promise.resolve(answerFor(trackIds));
      return new Promise(resolve => waiting.push(() => resolve(answerFor(trackIds))));
    },
    downloadHandBuiltPlaylist: async trackIds => {
      downloads.push(trackIds);
      if (trackIds.includes('gone')) throw new Error('Track 1 of the playlist is no longer playable from the library; remove it and try again');
      return {filename: 'hand-built-playlist.m3u', contents: '#EXTM3U\n', contentType: 'audio/x-mpegurl'};
    },
  };
  const playlistFile = {save: file => files.push(file)};
  const playlist = createHandBuiltPlaylist({store, explorerApi, playlistFile, eventBus: {publish: event => published.push(event), subscribe() {}}});
  const changes = () => published.filter(event => event.type === 'hand-built-playlist-changed');
  return {playlist, published, saved, files, asked, downloads, waiting, changes, last: () => changes().at(-1)};
}

const previewed = trackIds => { const {tracks, transitions} = answerFor(trackIds); return {trackIds, tracks, transitions}; };

test('the event types are the ones the use case publishes', () => {
  assert.deepEqual(HAND_BUILT_PLAYLIST_EVENT_TYPES, ['hand-built-playlist-changed', 'hand-built-playlist-track-chosen',
    'hand-built-playlist-download-started', 'hand-built-playlist-downloaded', 'hand-built-playlist-download-failed']);
});

test('a playlist kept in this browser comes back, then again with its preview', async () => {
  const {playlist, changes, asked} = harness({kept: ['a', 'b']});
  await playlist.restore();
  assert.deepEqual(asked, [['a', 'b']]);
  assert.deepEqual(changes(), [
    {type: 'hand-built-playlist-changed', trackIds: ['a', 'b'], notice: '', previewed: null},
    {type: 'hand-built-playlist-changed', trackIds: ['a', 'b'], notice: '', previewed: previewed(['a', 'b'])}]);
  assert.deepEqual(playlist.trackIds(), ['a', 'b']);
});

test('a kept playlist that cannot be read, or a browser that keeps nothing, starts empty and says so', async () => {
  for (const [options, notice] of [[{kept: 'nonsense'}, 'The playlist kept in this browser could not be read'],
    [{readFails: true}, 'This browser could not keep the playlist; it will be lost when the page reloads']]) {
    const {playlist, last, asked} = harness(options);
    await playlist.restore();
    assert.deepEqual(last(), {type: 'hand-built-playlist-changed', trackIds: [], notice, previewed: null});
    assert.deepEqual(asked, [], 'an empty playlist is not previewed');
  }
});

test('+ adds the neighbour, keeps the playlist, chooses the neighbour, and previews the playlist', async () => {
  const {playlist, published, saved, last} = harness();
  await playlist.restore();
  published.length = 0;
  await playlist.add({selectedTrackId: 'a', neighbourId: 'b'});
  assert.deepEqual(saved, [['a', 'b']]);
  assert.deepEqual(published.map(event => event.type), ['hand-built-playlist-changed', 'hand-built-playlist-track-chosen',
    'hand-built-playlist-changed']);
  assert.deepEqual(published[1], {type: 'hand-built-playlist-track-chosen', trackId: 'b'});
  assert.deepEqual(last().previewed, previewed(['a', 'b']));
});

test('+ on a track already in the playlist only chooses it', async () => {
  const {playlist, published, saved, asked} = harness({kept: ['a', 'b']});
  await playlist.restore();
  published.length = 0; saved.length = 0; asked.length = 0;
  await playlist.add({selectedTrackId: 'b', neighbourId: 'a'});
  assert.deepEqual(published, [{type: 'hand-built-playlist-track-chosen', trackId: 'a'}]);
  assert.deepEqual([saved, asked], [[], []], 'nothing is kept or asked again');
});

test('a change keeps the last preview until its own arrives, and an answer overtaken by a later change is dropped', async () => {
  const {playlist, waiting, changes} = harness({kept: ['a'], held: true});
  const restoring = playlist.restore();
  waiting.shift()();
  await restoring;
  const adding = playlist.add({selectedTrackId: 'a', neighbourId: 'b'});
  const addingMore = playlist.add({selectedTrackId: 'b', neighbourId: 'c'});
  assert.deepEqual(changes().at(-1).previewed, previewed(['a']), 'the rows already known keep their details');
  const [first, second] = waiting.splice(0);
  second();
  await addingMore;
  first();
  await adding;
  assert.deepEqual(changes().at(-1), {type: 'hand-built-playlist-changed', trackIds: ['a', 'b', 'c'], notice: '',
    previewed: previewed(['a', 'b', 'c'])});
});

test('a track no longer playable is in the preview asked for, but not among its tracks', async () => {
  const {playlist, last} = harness({kept: ['a', 'gone']});
  await playlist.restore();
  assert.deepEqual(last().previewed.trackIds, ['a', 'gone']);
  assert.deepEqual(last().previewed.tracks.map(track => track.trackId), ['a']);
});

test('a preview that fails says so and keeps the last one', async () => {
  const {playlist, last} = harness({kept: ['a']});
  await playlist.restore();
  await playlist.add({selectedTrackId: 'a', neighbourId: 'broken'});
  assert.deepEqual(last(), {type: 'hand-built-playlist-changed', trackIds: ['a', 'broken'],
    notice: "Could not show the playlist's details: Playlist preview failed", previewed: previewed(['a'])});
});

test('a track is removed, the playlist cleared, and each change kept', async () => {
  const {playlist, saved, last, asked} = harness({kept: ['a', 'b', 'c']});
  await playlist.restore();
  await playlist.remove('b');
  assert.deepEqual([last().trackIds, last().previewed], [['a', 'c'], previewed(['a', 'c'])]);
  asked.length = 0;
  await playlist.clear();
  assert.deepEqual(saved, [['a', 'c'], []]);
  assert.deepEqual([last().trackIds, last().previewed, asked], [[], null, []]);
});

test("a full playlist refuses the neighbour but still chooses it; a browser that cannot keep it says so", async () => {
  const full = Array.from({length: 500}, (_, place) => `t${place}`);
  const refusing = harness({kept: full});
  await refusing.playlist.restore();
  await refusing.playlist.add({selectedTrackId: 't0', neighbourId: 'more'});
  assert.deepEqual([refusing.last().trackIds.length, refusing.last().notice], [500, 'A playlist holds at most 500 tracks']);
  assert.deepEqual(refusing.published.at(-1), {type: 'hand-built-playlist-track-chosen', trackId: 'more'});
  const forgetful = harness({keepFails: true});
  await forgetful.playlist.restore();
  await forgetful.playlist.add({selectedTrackId: 'a', neighbourId: 'b'});
  assert.deepEqual([forgetful.last().trackIds, forgetful.last().notice],
    [['a', 'b'], 'This browser could not keep the playlist; it will be lost when the page reloads']);
});

test('the playlist downloads as an M3U file, and a refusal is published with its reason', async () => {
  const {playlist, published, files, downloads} = harness({kept: ['a', 'b']});
  await playlist.restore();
  published.length = 0;
  await playlist.download();
  assert.deepEqual(downloads, [['a', 'b']]);
  assert.deepEqual(files, [{filename: 'hand-built-playlist.m3u', contents: '#EXTM3U\n', contentType: 'audio/x-mpegurl'}]);
  assert.deepEqual(published.map(event => event.type), ['hand-built-playlist-download-started', 'hand-built-playlist-downloaded']);
  assert.equal(playlist.downloadState(), 'downloaded');
  await playlist.clear();
  await playlist.add({selectedTrackId: 'gone', neighbourId: 'a'});
  published.length = 0;
  await playlist.download();
  assert.deepEqual(published.at(-1), {type: 'hand-built-playlist-download-failed',
    message: 'Track 1 of the playlist is no longer playable from the library; remove it and try again'});
  assert.equal(playlist.downloadState(), 'failed');
});
