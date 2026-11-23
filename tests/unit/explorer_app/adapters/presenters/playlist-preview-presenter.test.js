// Issue #138: what the playlist preview shows for each preview event.
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {
  ENERGY_CHART, playlistEnergyChart, playlistPreviewViewModel, presentPlaylistPreviewEvent,
} from '../../../../../music_explorer/frameworks/explorer/assets/app/adapters/presenters/playlist-preview-presenter.js';

const track = (fields = {}) => ({trackId: 'a', title: 'Opening', artist: 'Synthetic', bpm: 120, key: 'A minor',
  camelot: '8A', arousal: 0.4, energyLevel: 0.25, energyTarget: 0.2, ...fields});

test('before any preview the panel offers Preview and shows nothing', () => {
  assert.deepEqual(playlistPreviewViewModel(), {previewDisabled: false, status: {text: '', urgent: false}, rows: [],
    chart: playlistEnergyChart([])});
});

test('while previewing, Preview is disabled and the listener is told', () => {
  assert.deepEqual(presentPlaylistPreviewEvent({type: 'playlist-preview-started'}),
    {previewDisabled: true, status: {text: 'Previewing the playlist…', urgent: false}});
});

test('a preview lists each track with its BPM, key, energy and the step into it', () => {
  const preview = {
    tracks: [track(), track({trackId: 'b', title: 'Lift', bpm: 122.5, key: 'C major', camelot: null, energyLevel: null,
      energyTarget: 0.6}), track({trackId: 'c', title: 'Drop', bpm: 110, key: null, camelot: null})],
    transitions: [
      {fromTrackId: 'a', toTrackId: 'b', keyCompatible: true, bpmStepSmooth: true, bpmChange: 2.5},
      {fromTrackId: 'b', toTrackId: 'c', keyCompatible: null, bpmStepSmooth: false, bpmChange: -12.5},
    ],
    complete: true, warning: null,
  };
  const {chart, ...listed} = presentPlaylistPreviewEvent({type: 'playlist-previewed', preview});
  assert.deepEqual(chart, playlistEnergyChart(preview.tracks));
  assert.deepEqual(listed, {
    previewDisabled: false,
    status: {text: '3 tracks.', urgent: false},
    rows: [
      {place: '1', track: 'Synthetic – Opening', bpm: '120.0', key: '8A', energy: '0.3', target: '0.2', transition: 'Start'},
      {place: '2', track: 'Synthetic – Lift', bpm: '122.5', key: 'C major', energy: '—', target: '0.6',
        transition: 'Key compatible, +2.5 BPM'},
      {place: '3', track: 'Synthetic – Drop', bpm: '110.0', key: '—', energy: '0.3', target: '0.2',
        transition: 'Key unknown, -12.5 BPM jump'},
    ],
  });
});

test('an incomplete preview says why, and a single track is one track', () => {
  const view = presentPlaylistPreviewEvent({type: 'playlist-previewed',
    preview: {tracks: [track()], transitions: [], complete: false, warning: 'Only 1 of 10 tracks fit'}});
  assert.deepEqual(view.status, {text: '1 track. Warning: Only 1 of 10 tracks fit', urgent: false});
});

test('a clash and an unknown step are told apart', () => {
  const view = presentPlaylistPreviewEvent({type: 'playlist-previewed', preview: {
    tracks: [track(), track({trackId: 'b'})], complete: true, warning: null,
    transitions: [{fromTrackId: 'a', toTrackId: 'b', keyCompatible: false, bpmStepSmooth: null, bpmChange: null}]}});
  assert.equal(view.rows[1].transition, 'Key clash, BPM change unknown');
});

test('a failed preview clears the list and alerts the listener', () => {
  assert.deepEqual(presentPlaylistPreviewEvent({type: 'playlist-preview-failed', message: 'bpm bounds must be ordered'}),
    {previewDisabled: false, status: {text: 'Preview failed: bpm bounds must be ordered', urgent: true}, rows: [],
      chart: playlistEnergyChart([])});
});

test('the energy chart places each track left to right, energy 0 at the foot and 1 at the head', () => {
  const {width, height, padding} = ENERGY_CHART;
  const chart = playlistEnergyChart([track({energyLevel: 0, energyTarget: 1}), track({energyLevel: 1, energyTarget: 0.5})]);
  const foot = height - padding, head = padding, middle = (foot + head) / 2;
  assert.deepEqual(chart.level, [[[padding, foot], [width - padding, head]]]);
  assert.deepEqual(chart.target, [[[padding, head], [width - padding, middle]]]);
  assert.equal(chart.label, 'Energy across 2 tracks: the arc target (dashed) and the energy each track reaches (solid).');
});

test('an unknown energy breaks the line instead of inventing a value', () => {
  const chart = playlistEnergyChart([track({energyLevel: 0.2}), track({energyLevel: null}), track({energyLevel: 0.4}),
    track({energyLevel: 0.6})]);
  assert.deepEqual(chart.level.map(segment => segment.length), [1, 2]);
  assert.deepEqual(playlistEnergyChart([track({energyTarget: null})]).target, []);
});

test('a single track sits in the middle, and no tracks draw no lines', () => {
  const [[[x]]] = playlistEnergyChart([track()]).level;
  assert.equal(x, ENERGY_CHART.width / 2);
  assert.deepEqual(playlistEnergyChart([]), {...ENERGY_CHART, level: [], target: [], label: 'No energy to chart yet.'});
});
