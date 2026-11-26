// Issue #278: building a playlist by hand from the graph's labels, kept in this browser, and downloading it as an M3U.
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {createHandBuiltPlaylist} from '../../../../../music_explorer/frameworks/explorer/assets/app/application/build-playlist/build-playlist.js';
import {HAND_BUILT_PLAYLIST_EVENT_TYPES} from '../../../../../music_explorer/frameworks/explorer/assets/app/application/build-playlist/hand-built-playlist-events.js';

const label = trackId => ({trackId, title: 'Track ' + trackId, artist: 'Synthetic'});

function harness({kept = null, keepFails = false, readFails = false} = {}) {
  const published = [], saved = [], files = [], asked = [], downloads = [];
  const store = {
    load() { if (readFails) throw new Error('blocked'); return kept; },
    save(trackIds) { if (keepFails) throw new Error('quota'); saved.push(trackIds); },
  };
  const explorerApi = {
    labelTracks: async trackIds => { asked.push(trackIds); return trackIds.filter(id => id !== 'unknown').map(label); },
    downloadHandBuiltPlaylist: async trackIds => {
      downloads.push(trackIds);
      if (trackIds.includes('gone')) throw new Error('Track 1 of the playlist is no longer playable from the library; remove it and try again');
      return {filename: 'hand-built-playlist.m3u', contents: '#EXTM3U\n', contentType: 'audio/x-mpegurl'};
    },
  };
  const playlistFile = {save: file => files.push(file)};
  const playlist = createHandBuiltPlaylist({store, explorerApi, playlistFile, eventBus: {publish: event => published.push(event), subscribe() {}}});
  const changes = () => published.filter(event => event.type === 'hand-built-playlist-changed');
  return {playlist, published, saved, files, asked, downloads, changes, last: () => changes().at(-1)};
}

test('the event types are the ones the use case publishes', () => {
  assert.deepEqual(HAND_BUILT_PLAYLIST_EVENT_TYPES, ['hand-built-playlist-changed', 'hand-built-playlist-track-chosen',
    'hand-built-playlist-download-started', 'hand-built-playlist-downloaded', 'hand-built-playlist-download-failed']);
});

test('a playlist kept in this browser comes back, with its tracks labelled', async () => {
  const {playlist, last, asked} = harness({kept: ['a', 'b']});
  await playlist.restore();
  assert.deepEqual(asked, [['a', 'b']]);
  assert.deepEqual(last(), {type: 'hand-built-playlist-changed', trackIds: ['a', 'b'], labels: [label('a'), label('b')], notice: ''});
  assert.deepEqual(playlist.trackIds(), ['a', 'b']);
});

test('a kept playlist that cannot be read, or a browser that keeps nothing, starts empty and says so', async () => {
  for (const [options, notice] of [[{kept: 'nonsense'}, 'The playlist kept in this browser could not be read'],
    [{readFails: true}, 'This browser could not keep the playlist; it will be lost when the page reloads']]) {
    const {playlist, last, asked} = harness(options);
    await playlist.restore();
    assert.deepEqual(last(), {type: 'hand-built-playlist-changed', trackIds: [], labels: [], notice});
    assert.deepEqual(asked, []);
  }
});

test('+ adds the neighbour, keeps the playlist, and chooses the neighbour as the next selection', async () => {
  const {playlist, published, saved, last} = harness();
  await playlist.restore();
  published.length = 0;
  await playlist.add({selectedTrackId: 'a', neighbourId: 'b'});
  assert.deepEqual(saved, [['a', 'b']]);
  assert.deepEqual(published.map(event => event.type), ['hand-built-playlist-changed', 'hand-built-playlist-track-chosen',
    'hand-built-playlist-changed']);
  assert.deepEqual(published[1], {type: 'hand-built-playlist-track-chosen', trackId: 'b'});
  assert.deepEqual(last().labels, [label('a'), label('b')]);
});

test('+ on a track already in the playlist only chooses it', async () => {
  const {playlist, published, saved, asked} = harness({kept: ['a', 'b']});
  await playlist.restore();
  published.length = 0; saved.length = 0; asked.length = 0;
  await playlist.add({selectedTrackId: 'b', neighbourId: 'a'});
  assert.deepEqual(published, [{type: 'hand-built-playlist-track-chosen', trackId: 'a'}]);
  assert.deepEqual([saved, asked], [[], []], 'nothing is kept or asked again');
});

test('only tracks not yet labelled are asked for, at most a hundred at a time', async () => {
  const many = Array.from({length: 150}, (_, place) => `t${place}`);
  const {playlist, asked, last} = harness({kept: many});
  await playlist.restore();
  assert.deepEqual(asked.map(trackIds => trackIds.length), [100, 50]);
  asked.length = 0;
  await playlist.add({selectedTrackId: 't0', neighbourId: 'unknown'});
  assert.deepEqual(asked, [['unknown']]);
  assert.equal(last().labels.length, 150, 'a track the server cannot label has none');
});

test('a track is removed, the playlist cleared, and each change kept', async () => {
  const {playlist, saved, last} = harness({kept: ['a', 'b', 'c']});
  await playlist.restore();
  await playlist.remove('b');
  assert.deepEqual([last().trackIds, last().labels.map(each => each.trackId)], [['a', 'c'], ['a', 'c']]);
  await playlist.clear();
  assert.deepEqual(saved, [['a', 'c'], []]);
  assert.deepEqual([last().trackIds, last().labels], [[], []]);
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
