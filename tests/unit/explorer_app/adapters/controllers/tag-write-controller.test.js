// Issue #132: the Write tags panel's commands, validated before the use case sees them.
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {tagWriteController} from '../../../../../music_explorer/frameworks/explorer/assets/app/adapters/controllers/tag-write-controller.js';

function harness(currentTrackId) {
  const calls = [], rejected = [];
  const controller = tagWriteController({currentTrackId: () => currentTrackId, rejectInput: message => rejected.push(message),
    tagWrite: {preview: async request => calls.push(['preview', request]), apply: async () => calls.push(['apply']), discard: () => calls.push(['discard'])}});
  return {controller, calls, rejected};
}

test('a preview covers the selected track with the chosen policy, and an apply follows it', async () => {
  const {controller, calls} = harness('sha256:a');
  await controller.previewRequested('replace-existing');
  await controller.applyRequested();
  assert.deepEqual(calls, [['preview', {trackIds: ['sha256:a'], policy: 'replace-existing'}], ['apply']]);
});

test('without a selected track or with an unknown policy nothing is previewed', async () => {
  const none = harness(null);
  await none.controller.previewRequested('fill-empty');
  assert.deepEqual([none.calls, none.rejected], [[], ['Select a track to tag first']]);
  const odd = harness('sha256:a');
  await odd.controller.previewRequested('overwrite');
  assert.deepEqual([odd.calls, odd.rejected], [[], ['Choose whether to fill empty tags only or also replace existing ones']]);
});

test('a change of track discards the preview', () => {
  const {controller, calls} = harness('sha256:a');
  controller.trackChanged();
  assert.deepEqual(calls, [['discard']]);
});
