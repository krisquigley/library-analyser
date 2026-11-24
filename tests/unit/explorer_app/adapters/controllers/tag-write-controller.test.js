// Issue #132: the Write tags panel's commands, validated before the use case sees them.
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {tagWriteController} from '../../../../../music_explorer/frameworks/explorer/assets/app/adapters/controllers/tag-write-controller.js';

function harness(currentTrackId) {
  const calls = [], rejected = [];
  const record = name => (...args) => { calls.push([name, ...args]); };
  const controller = tagWriteController({currentTrackId: () => currentTrackId, rejectInput: message => rejected.push(message),
    tagWrite: {previewSelectedTrack: record('track'), previewOfferedPlaylist: record('playlist'), apply: record('apply'),
      discard: record('discard'), offerPlaylist: record('offer'), withdrawPlaylist: record('withdraw')}});
  return {controller, calls, rejected};
}

test('a preview covers the selected track or the previewed playlist, with the chosen policy', async () => {
  const {controller, calls} = harness('sha256:a');
  await controller.previewRequested('replace-existing', 'selected-track');
  await controller.previewRequested('fill-empty', 'previewed-playlist');
  await controller.applyRequested();
  assert.deepEqual(calls, [['track', {trackId: 'sha256:a', policy: 'replace-existing'}],
    ['playlist', {policy: 'fill-empty'}], ['apply']]);
});

test('without a selected track, or with an unknown policy or target, nothing is previewed', async () => {
  const none = harness(null);
  await none.controller.previewRequested('fill-empty', 'selected-track');
  assert.deepEqual([none.calls, none.rejected], [[], ['Select a track to tag first']]);
  const odd = harness('sha256:a');
  await odd.controller.previewRequested('overwrite', 'selected-track');
  await odd.controller.previewRequested('fill-empty', 'library');
  assert.deepEqual([odd.calls, odd.rejected], [[], ['Choose whether to fill empty tags only or also replace existing ones',
    'Choose the selected track or the previewed playlist']]);
});

test('a change of track discards the preview; a playlist preview offers or withdraws its tracks', () => {
  const {controller, calls} = harness('sha256:a');
  controller.trackChanged();
  controller.playlistPreviewed([{trackId: 'x'}, {trackId: 'y'}]);
  controller.playlistPreviewCleared();
  assert.deepEqual(calls, [['discard'], ['offer', ['x', 'y']], ['withdraw']]);
});
