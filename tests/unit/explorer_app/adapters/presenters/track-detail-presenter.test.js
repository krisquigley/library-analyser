// Issue #146: what the track detail panel shows.
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {detailFieldViewModel, scoreGaugeViewModel, trackDetailFailureViewModel, trackDetailLoadingViewModel, trackDetailViewModel,
  trackMetadataViewModel} from '../../../../../music_explorer/frameworks/explorer/assets/app/adapters/presenters/track-detail-presenter.js';

const MOOD_MODEL = 'mtg_jamendo_moodtheme-discogs-effnet-1';
const text = items => items.map(item => item.text ?? `gauge ${item.gauge.label}`);

test('a manual override is shown instead of the automatic evidence', () => {
  assert.deepEqual(detailFieldViewModel('mood', {manual_text: 'Calm', typed_override_status: 'resolved'}),
    {name: 'mood', items: [{text: 'Manual override: Calm (resolved; automatic evidence not displayed)'}]});
  assert.deepEqual(text(detailFieldViewModel('key', {manual_text: 'A'}).items), ['Manual override: A (unresolved; automatic evidence not displayed)']);
});

test('scores show the scale, then a gauge for each of the first twelve, then how many more', () => {
  const values = Array.from({length: 14}, (_, i) => [`label${String(i).padStart(2, '0')}`, 0.9 - i * 0.01]);
  const items = detailFieldViewModel('mood', {automatic: {values, provenance: [[MOOD_MODEL, '1']]}}).items;
  assert.equal(items[0].text, 'display scores > 0.1 (raw 0–1 labelled scores; not probabilities; independent of analysis cutoff).');
  assert.equal(items.filter(item => item.gauge).length, 12);
  assert.equal(items.at(-1).text, '2 more significant labels not shown');
});

test('scores without usable evidence, or none significant, say so', () => {
  assert.deepEqual(text(detailFieldViewModel('genres', {automatic: {values: [], provenance: []}, missing_reason: 'not analysed'}).items),
    ['no usable evidence (unsupported or missing model/scale)', 'not analysed']);
  const weak = {automatic: {values: [['calm', 0.05]], provenance: [[MOOD_MODEL, '1']]}};
  assert.equal(text(detailFieldViewModel('mood', weak).items)[1], 'no significant values');
  const none = {automatic: {values: [], provenance: [[MOOD_MODEL, '1']]}};
  assert.equal(text(detailFieldViewModel('mood', none).items)[1], 'no usable evidence');
});

test('energy, BPM, key and other fields', () => {
  const energy = {automatic: {values: [['valence', 4.24], ['arousal', 5.06]], provenance: [['emomusic-msd-musicnn-2', '1']]}};
  assert.deepEqual(text(detailFieldViewModel('energy', energy).items),
    ['valence: 4.2 · arousal: 5.1 (Emomusic native regression scale; not a 0–1 probability)']);
  assert.deepEqual(text(detailFieldViewModel('energy', {automatic: {provenance: []}}).items),
    ['no usable evidence (unsupported model or contradictory scale)']);
  assert.deepEqual(text(detailFieldViewModel('bpm', {automatic: {values: [['bpm', 122.44]]}}).items), ['122.4 BPM (raw)']);
  assert.deepEqual(text(detailFieldViewModel('key', {automatic: {values: [['key', 'A minor']]}, missing_reason: 'low strength'}).items),
    ['A minor', 'low strength']);
  assert.deepEqual(text(detailFieldViewModel('bpm', {automatic: {}}).items), ['no usable evidence']);
  assert.deepEqual(text(detailFieldViewModel('loudness', {}).items), ['no usable evidence (no supported display scale)']);
});

test('a gauge names its score out of 1 and turns its needle over 240 degrees', () => {
  assert.deepEqual(scoreGaugeViewModel('calm', 0.25), {label: 'calm', ariaLabel: 'calm: 0.3 out of 1', needleDegrees: -60});
});

test('metadata rows use friendly labels, merge aliases and skip blanks and repeats', () => {
  assert.deepEqual(trackMetadataViewModel({common: [['title', 'Song'], ['albumartist', 'Band'], ['Title', 'Again'], ['comment', ' ']],
    tags: [['TPE2', ['Other']], ['mood', ['calm', ' ', 'warm']]]}),
  {lines: ['Title: Song', 'Album artist: Band', 'mood: calm; warm']});
  assert.deepEqual(trackMetadataViewModel(undefined), {lines: ['No embedded textual metadata found']});
});

test('the detail shows its metadata, then each field in order', () => {
  const detail = trackDetailViewModel({metadata: {common: [['title', 'Song']]}, fields: {bpm: {automatic: {values: [['bpm', 120]]}}}});
  assert.deepEqual([detail.heading, detail.metadata.lines, detail.fields.map(field => field.name)], ['Current Track', ['Title: Song'], ['bpm']]);
});

test('while the detail loads, and when it fails, the panel says so', () => {
  assert.deepEqual(trackDetailLoadingViewModel(), {status: 'Loading current track detail…'});
  assert.deepEqual(trackDetailFailureViewModel(new Error('Unknown track')), {alert: 'Unable to load current track detail: Unknown track'});
  assert.deepEqual(trackDetailFailureViewModel('offline'), {alert: 'Unable to load current track detail: offline'});
});

test('the detail leaves out the reasons the evidence is provisional', () => {
  const detail = trackDetailViewModel({reasons: ['genres: provisional, uncalibrated scores', 'energy: uncertainty'],
    metadata: {common: [['title', 'A']], tags: []}, fields: {}});
  assert.deepEqual([detail.heading, detail.metadata.lines, detail.fields], ['Current Track', ['Title: A'], []]);
  assert.ok(!JSON.stringify(detail).includes('provisional') && !JSON.stringify(detail).includes('uncertainty'));
});
