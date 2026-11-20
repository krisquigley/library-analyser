// Issue #146: the Download M3U controls' input, validated against its schema before the use case sees it.
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {playlistDownloadController} from '../../../../../music_explorer/frameworks/explorer/assets/app/adapters/controllers/playlist-download-controller.js';

function harness() {
  const edits = [];
  const downloads = [];
  const rejected = [];
  const arcCommands = [];
  const playlistDownload = {
    edit: changes => edits.push(changes), download: async trackId => downloads.push(trackId),
    addArc: () => arcCommands.push(['add']), removeArc: place => arcCommands.push(['remove', place]),
    moveArc: (place, offset) => arcCommands.push(['move', place, offset]),
    editArc: (place, changes) => arcCommands.push(['edit', place, changes]),
  };
  const controller = playlistDownloadController({
    playlistDownload, currentTrackId: () => 'track-1', rejectInput: message => rejected.push(message)});
  return {controller, edits, downloads, rejected, arcCommands};
}

test('valid control values reach the draft as they are', () => {
  const {controller, edits, rejected} = harness();
  controller.controlsEdited({bpmMin: ' 120 ', count: '', harmonicMixing: false, arcLengthUnit: 'minutes', moodHold: 'happy'});
  assert.deepEqual(edits, [{bpmMin: ' 120 ', count: '', harmonicMixing: false, arcLengthUnit: 'minutes', moodHold: 'happy'}]);
  assert.deepEqual(rejected, []);
});

test('invalid control values are rejected with a message and never reach the draft', () => {
  const cases = [
    [{bpmMin: 'fast'}, 'Min BPM must be a number'],
    [{count: 10}, 'Track count must be a number'],
    [{durationMinutes: 'Infinity'}, 'Duration must be a number'],
    [{harmonicMixing: 'yes'}, 'Harmonic mixing must be on or off'],
    [{arcLengthUnit: 'beats'}, 'Arc length unit must be one of: tracks, minutes'],
    [{energyArc: 'peak'}, 'Unknown playlist control: energyArc'],
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

test('arc commands reach the use case, and a valid arc edit passes its values as they are', () => {
  const {controller, arcCommands, rejected} = harness();
  controller.arcAdded();
  controller.arcEdited(0, {shape: 'peak', length: ' 6 ', low: '', high: '0.9'});
  controller.arcMoved(1, -1);
  controller.arcRemoved(0);
  assert.deepEqual(arcCommands, [
    ['add'], ['edit', 0, {shape: 'peak', length: ' 6 ', low: '', high: '0.9'}], ['move', 1, -1], ['remove', 0]]);
  assert.deepEqual(rejected, []);
});

test('an invalid arc edit is rejected with a message and never reaches the use case', () => {
  const cases = [
    [{shape: 'zigzag'}, 'Arc shape must be one of: steady, rise, fall, peak, dip'],
    [{length: 'long'}, 'Arc length must be a number'],
    [{low: 'Infinity'}, 'Arc energy low must be a number'],
    [{high: 1}, 'Arc energy high must be a number'],
    [{colour: 'red'}, 'Unknown energy arc field: colour'],
  ];
  for (const [fields, message] of cases) {
    const {controller, arcCommands, rejected} = harness();
    controller.arcEdited(0, fields);
    assert.deepEqual(arcCommands, [], JSON.stringify(fields));
    assert.deepEqual(rejected, [message]);
  }
});
