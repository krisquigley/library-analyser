// Issue #146: the Download M3U controls' input, validated against its schema before the use case sees it.
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {playlistDownloadController} from '../../../../../music_explorer/frameworks/explorer/assets/app/adapters/controllers/playlist-download-controller.js';

function harness() {
  const edits = [];
  const downloads = [];
  const rejected = [];
  const playlistDownload = {edit: changes => edits.push(changes), download: async trackId => downloads.push(trackId)};
  const controller = playlistDownloadController({
    playlistDownload, currentTrackId: () => 'track-1', rejectInput: message => rejected.push(message)});
  return {controller, edits, downloads, rejected};
}

test('valid control values reach the draft as they are', () => {
  const {controller, edits, rejected} = harness();
  controller.controlsEdited({bpmMin: ' 120 ', count: '', harmonicMixing: false, energyArc: 'peak', moodHold: 'happy'});
  assert.deepEqual(edits, [{bpmMin: ' 120 ', count: '', harmonicMixing: false, energyArc: 'peak', moodHold: 'happy'}]);
  assert.deepEqual(rejected, []);
});

test('invalid control values are rejected with a message and never reach the draft', () => {
  const cases = [
    [{bpmMin: 'fast'}, 'Min BPM must be a number'],
    [{count: 10}, 'Track count must be a number'],
    [{energyHigh: 'Infinity'}, 'Energy high must be a number'],
    [{harmonicMixing: 'yes'}, 'Harmonic mixing must be on or off'],
    [{energyArc: 'zigzag'}, 'Energy arc must be one of: none, steady, rise, fall, peak, dip'],
    [{moodHold: 3}, 'Mood hold must be text'],
    [{tempo: '120'}, 'Unknown playlist control: tempo'],
  ];
  for (const [controls, message] of cases) {
    const {controller, edits, rejected} = harness();
    controller.controlsEdited(controls);
    assert.deepEqual(edits, [], JSON.stringify(controls));
    assert.deepEqual(rejected, [message]);
  }
});

test('a download request records the controls, then downloads from the selected track', async () => {
  const {controller, edits, downloads} = harness();
  await controller.downloadRequested({count: '25'});
  assert.deepEqual(edits, [{count: '25'}]);
  assert.deepEqual(downloads, ['track-1']);
});

test('a download request with invalid controls does not download', async () => {
  const {controller, downloads, rejected} = harness();
  await controller.downloadRequested({count: 'many'});
  assert.deepEqual(downloads, []);
  assert.deepEqual(rejected, ['Track count must be a number']);
});
