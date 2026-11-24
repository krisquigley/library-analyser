// Issue #138: what the playlist preview shows for each preview event.
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {
  ENERGY_CHART, playlistEnergyChart, playlistPreviewViewModel, playlistReadinessViewModel, presentPlaylistPreviewEvent,
} from '../../../../../music_explorer/frameworks/explorer/assets/app/adapters/presenters/playlist-preview-presenter.js';
import {trackPlaybackViewModel} from '../../../../../music_explorer/frameworks/explorer/assets/app/adapters/presenters/track-playback-presenter.js';

const track = (fields = {}) => ({trackId: 'a', title: 'Opening', artist: 'Synthetic', bpm: 120, key: 'A minor',
  camelot: '8A', arousal: 0.4, energyLevel: 0.25, energyTarget: 0.2, durationSeconds: 240, ...fields});

test('before any preview the panel offers Preview and shows nothing', () => {
  assert.deepEqual(playlistPreviewViewModel(), {previewDisabled: false, status: {text: '', urgent: false}, rows: [],
    chart: playlistEnergyChart([]), playback: trackPlaybackViewModel()});
});

test('while previewing, Preview is disabled and the listener is told', () => {
  assert.deepEqual(presentPlaylistPreviewEvent({type: 'playlist-preview-started'}),
    {previewDisabled: true, status: {text: 'Previewing the playlist…', urgent: false}});
});

test('a preview lists each track with its BPM, key in letters (#261), energy and the step into it', () => {
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
    status: {text: '3 tracks · 12:00.', urgent: false},
    rows: [
      {trackId: 'a', place: '1', track: 'Synthetic – Opening', length: '4:00', bpm: '120.0', key: 'A minor', energy: '0.3', target: '0.2', transition: 'Start'},
      {trackId: 'b', place: '2', track: 'Synthetic – Lift', length: '4:00', bpm: '122.5', key: 'C major', energy: '—', target: '0.6',
        transition: 'Key compatible, +2.5 BPM'},
      {trackId: 'c', place: '3', track: 'Synthetic – Drop', length: '4:00', bpm: '110.0', key: '—', energy: '0.3', target: '0.2',
        transition: 'Key unknown, -12.5 BPM jump'},
    ],
  });
});

test('an incomplete preview says why, and a single track is one track', () => {
  const view = presentPlaylistPreviewEvent({type: 'playlist-previewed',
    preview: {tracks: [track()], transitions: [], complete: false, warning: 'Only 1 of 10 tracks fit'}});
  assert.deepEqual(view.status, {text: '1 track · 4:00. Warning: Only 1 of 10 tracks fit', urgent: false});
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

test('Preview waits, with the reason, until the recipe is complete, and the missing controls are named (#234)', () => {
  assert.deepEqual(playlistReadinessViewModel([{control: 'start', reason: 'Select a start track first'},
    {control: 'bpmMin', reason: 'Enter a minimum BPM'}]),
  {readiness: {ready: false, reason: 'To preview: select a start track first, enter a minimum BPM.'}, missing: ['start', 'bpmMin']});
  assert.deepEqual(playlistReadinessViewModel([]), {readiness: {ready: true, reason: ''}, missing: []});
});

test('a track without a title or artist tag is named by what it has (#255)', () => {
  const rows = presentPlaylistPreviewEvent({type: 'playlist-previewed', preview: {complete: true, warning: null, transitions: [],
    tracks: [track({title: ''}), track({trackId: 'b', artist: ''}), track({trackId: 'c', title: '', artist: ''})]}}).rows;
  assert.deepEqual(rows.map(row => row.track), ['Synthetic', 'Opening', 'Untitled track']);
});

test("each track shows its length, and the summary the playlist's, counting the tracks whose length is unknown (#257)", () => {
  const previewed = durations => presentPlaylistPreviewEvent({type: 'playlist-previewed', preview: {complete: true, warning: null,
    transitions: [], tracks: durations.map((durationSeconds, place) => track({trackId: String(place), durationSeconds}))}});
  const mixed = previewed([225.4, null, 3600]);
  assert.deepEqual(mixed.rows.map(row => row.length), ['3:45', '—', '1:00:00']);
  assert.equal(mixed.status.text, '3 tracks · 1:03:45, plus 1 of unknown length.');
  assert.equal(previewed([null, null]).status.text, '2 tracks · length unknown.');
});
