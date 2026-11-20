// Issue #138: what the playlist preview shows for each preview event.
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {
  playlistPreviewViewModel, presentPlaylistPreviewEvent,
} from '../../../../../music_explorer/frameworks/explorer/assets/app/adapters/presenters/playlist-preview-presenter.js';

const track = (fields = {}) => ({trackId: 'a', title: 'Opening', artist: 'Synthetic', bpm: 120, key: 'A minor',
  camelot: '8A', arousal: 0.4, energyLevel: 0.25, energyTarget: 0.2, ...fields});

test('before any preview the panel offers Preview and shows nothing', () => {
  assert.deepEqual(playlistPreviewViewModel(), {previewDisabled: false, status: {text: '', urgent: false}, rows: []});
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
  assert.deepEqual(presentPlaylistPreviewEvent({type: 'playlist-previewed', preview}), {
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
    {previewDisabled: false, status: {text: 'Preview failed: bpm bounds must be ordered', urgent: true}, rows: []});
});
