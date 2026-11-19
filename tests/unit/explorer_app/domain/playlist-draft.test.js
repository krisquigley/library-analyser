// Issue #146: the playlist the listener is drafting in the Download M3U controls.
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {
  EMPTY_PLAYLIST_DRAFT, editPlaylistDraft, energyRangeApplies, minimumKeyStrengthApplies, playlistRecipeOf,
} from '../../../../music_explorer/frameworks/explorer/assets/app/domain/playlist-draft.js';

test('a new draft asks for ten tracks with harmonic mixing and no arc', () => {
  assert.deepEqual(EMPTY_PLAYLIST_DRAFT, {
    bpmMin: '', bpmMax: '', count: '10', durationMinutes: '', harmonicMixing: true, minimumKeyStrength: '0.5',
    energyArc: 'none', energyLow: '', energyHigh: '', moodHold: '',
  });
  assert.ok(Object.isFrozen(EMPTY_PLAYLIST_DRAFT));
});

test('editing a draft returns a new draft and leaves the old one as it was', () => {
  const edited = editPlaylistDraft(EMPTY_PLAYLIST_DRAFT, {bpmMin: '120', energyArc: 'rise'});
  assert.equal(edited.bpmMin, '120');
  assert.equal(edited.energyArc, 'rise');
  assert.equal(edited.count, '10');
  assert.equal(EMPTY_PLAYLIST_DRAFT.bpmMin, '');
  assert.ok(Object.isFrozen(edited));
});

test('a draft refuses a control it does not have', () => {
  assert.throws(() => editPlaylistDraft(EMPTY_PLAYLIST_DRAFT, {tempo: '120'}), /Unknown playlist control: tempo/);
});

test('the minimum key strength applies only with harmonic mixing on', () => {
  assert.equal(minimumKeyStrengthApplies(EMPTY_PLAYLIST_DRAFT), true);
  assert.equal(minimumKeyStrengthApplies(editPlaylistDraft(EMPTY_PLAYLIST_DRAFT, {harmonicMixing: false})), false);
});

test('an energy range applies only with an energy arc', () => {
  assert.equal(energyRangeApplies(EMPTY_PLAYLIST_DRAFT), false);
  assert.equal(energyRangeApplies(editPlaylistDraft(EMPTY_PLAYLIST_DRAFT, {energyArc: 'peak'})), true);
});

test('a draft becomes the recipe for the selected start track', () => {
  const draft = editPlaylistDraft(EMPTY_PLAYLIST_DRAFT, {
    bpmMin: '120', bpmMax: '128', durationMinutes: '45', energyArc: 'rise', energyHigh: '0.7', moodHold: 'happy'});
  assert.deepEqual(playlistRecipeOf(draft, 'track-start'), {
    startTrackId: 'track-start', bpmMin: '120', bpmMax: '128', length: {durationMinutes: '45'},
    harmonicMixing: true, minimumKeyStrength: '0.5', energyArc: {shape: 'rise', low: null, high: '0.7'},
    moodHold: 'happy',
  });
});

test('a draft without a start track has no recipe', () => {
  assert.throws(() => playlistRecipeOf(EMPTY_PLAYLIST_DRAFT, null), /Select a start track before downloading M3U/);
});
