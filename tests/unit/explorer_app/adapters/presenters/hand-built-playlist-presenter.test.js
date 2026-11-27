// Issue #278: what the strip over the graph shows of the hand-built playlist and its download.
// Issue #287: the strip is a table like the playlist preview's, from the playlist's last preview.
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {
  handBuiltPlaylistViewModel, presentHandBuiltPlaylistDownload,
} from '../../../../../music_explorer/frameworks/explorer/assets/app/adapters/presenters/hand-built-playlist-presenter.js';

const track = (trackId, fields = {}) => ({trackId, title: 'Title ' + trackId, artist: 'Synthetic', bpm: 120, key: 'C major',
  camelot: '8B', arousal: 4.25, energyTarget: null, durationSeconds: 200, ...fields});
const step = (fromTrackId, toTrackId, fields = {}) => ({fromTrackId, toTrackId, keyCompatible: true, bpmStepSmooth: true,
  bpmChange: 4, ...fields});

test('each track is a row like the playlist preview’s, in the listener’s order, with the step into it', () => {
  const previewed = {trackIds: ['a', 'b'], tracks: [track('a'), track('b', {bpm: 124, key: null, arousal: null, durationSeconds: 95})],
    transitions: [step('a', 'b')]};
  const model = handBuiltPlaylistViewModel({trackIds: ['a', 'b'], notice: '', previewed});
  assert.deepEqual(model, {
    hidden: false, heading: 'Your playlist · 2 tracks · 4:55', downloadDisabled: false, clearDisabled: false,
    rows: [
      {trackId: 'a', place: '1', track: 'Synthetic – Title a', length: '3:20', bpm: '120.0', key: 'C major', energy: '4.3',
        transition: 'Start', playable: true, removeLabel: 'Remove Synthetic – Title a from your playlist',
        earlierLabel: 'Move Synthetic – Title a earlier', laterLabel: 'Move Synthetic – Title a later', first: true, last: false},
      {trackId: 'b', place: '2', track: 'Synthetic – Title b', length: '1:35', bpm: '124.0', key: '—', energy: '—',
        transition: 'Key compatible, +4.0 BPM', playable: true, removeLabel: 'Remove Synthetic – Title b from your playlist',
        earlierLabel: 'Move Synthetic – Title b earlier', laterLabel: 'Move Synthetic – Title b later', first: false, last: true}],
    notice: {text: '', urgent: false}});
});

test('a track not yet previewed waits, one no longer playable says so, and a step not previewed is unknown', () => {
  const previewed = {trackIds: ['a', 'gone', 'b'], tracks: [track('a'), track('b')], transitions: [step('a', 'b')]};
  const model = handBuiltPlaylistViewModel({trackIds: ['b', 'gone', 'a', 'new'], notice: '', previewed});
  assert.equal(model.heading, 'Your playlist · 4 tracks · 6:40');
  assert.deepEqual(model.rows.map(row => [row.place, row.track, row.length, row.transition, row.playable, row.removeLabel]), [
    ['1', 'Synthetic – Title b', '3:20', 'Start', true, 'Remove Synthetic – Title b from your playlist'],
    ['2', 'No longer playable from the library', '—', '—', false, 'Remove track 2 from your playlist'],
    ['3', 'Synthetic – Title a', '3:20', '—', true, 'Remove Synthetic – Title a from your playlist'],
    ['4', 'Track 4', '…', '…', true, 'Remove track 4 from your playlist']]);
});

test('one track is counted as one, and an empty playlist hides the strip unless there is something to say', () => {
  assert.equal(handBuiltPlaylistViewModel({trackIds: ['a'], notice: '', previewed: null}).heading, 'Your playlist · 1 track');
  const empty = handBuiltPlaylistViewModel({trackIds: [], notice: '', previewed: null});
  assert.deepEqual([empty.hidden, empty.downloadDisabled, empty.clearDisabled, empty.rows], [true, true, true, []]);
  const told = handBuiltPlaylistViewModel({trackIds: [], notice: 'The playlist kept in this browser could not be read', previewed: null});
  assert.deepEqual([told.hidden, told.notice], [false, {text: 'The playlist kept in this browser could not be read', urgent: true}]);
});

test('the download says what it is doing, and why it failed', () => {
  assert.deepEqual(['hand-built-playlist-download-started', 'hand-built-playlist-downloaded'].map(type => presentHandBuiltPlaylistDownload({type})), [
    {text: 'Preparing the M3U…', urgent: false}, {text: 'M3U downloaded', urgent: false}]);
  assert.deepEqual(presentHandBuiltPlaylistDownload({type: 'hand-built-playlist-download-failed', message: 'Track 2 is gone'}),
    {text: 'Could not download the playlist: Track 2 is gone', urgent: true});
});

test('#293: a track not yet previewed or no longer playable can still be moved, named by its place', () => {
  const model = handBuiltPlaylistViewModel({trackIds: ['a', 'gone', 'new'], notice: '',
    previewed: {trackIds: ['a', 'gone'], tracks: [track('a')], transitions: []}});
  assert.deepEqual(model.rows.map(row => [row.earlierLabel, row.laterLabel, row.first, row.last]), [
    ['Move Synthetic – Title a earlier', 'Move Synthetic – Title a later', true, false],
    ['Move track 2 earlier', 'Move track 2 later', false, false],
    ['Move track 3 earlier', 'Move track 3 later', false, true]]);
});
