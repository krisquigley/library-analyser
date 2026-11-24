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

test('metadata is one flat list: tag aliases merge, the first of a repeated key wins, and markup stays text', () => {
  const metadata = trackMetadataViewModel({common: [['title', 'Song'], ['album artist', 'Band']],
    tags: [['TITLE', ['Other']], ['ALBUM_ARTIST', ['Other Band']], ['comment', ['<script>']], ['genre', ['Rock']], ['genre', ['Jazz']],
      ['TRACKNUMBER', ['4']], ['TPE2', ['Other Band']]], warnings: ['diagnostic warning']});
  assert.deepEqual(metadata, {lines: ['Title: Song', 'Album artist: Band', 'Comment: <script>', 'Genre: Rock', 'Track number: 4']});
  assert.deepEqual(trackMetadataViewModel({}), {lines: ['No embedded textual metadata found']});
});

test('the current track shows no run diagnostics or graph key', () => {
  const detail = trackDetailViewModel({handle: 'track-1', display_label: 'Alpha.flac', latest_run_status: 'completed',
    available_locations: 1, reasons: ['ready'], warnings: ['diagnostic warning'], diagnostics: {graph: 'key'}, fields: {}});
  assert.deepEqual(Object.keys(detail).sort(), ['fields', 'heading', 'metadata', 'unavailable']);
  assert.ok(!/completed|diagnostic|Display|graph/i.test(JSON.stringify(detail)), JSON.stringify(detail));
});

const ENERGY_MODEL = 'emomusic-msd-musicnn-2';

test('key facts lead the detail: BPM, key, the energy axes as measured, and duration; an override wins and says so (#236)', () => {
  const detail = trackDetailViewModel({metadata: {common: [['title', 'Song']], duration_seconds: 225.4}, fields: {
    bpm: {automatic: {values: [['bpm', 122.44]]}},
    key: {manual_text: '9A', typed_override_status: 'resolved', automatic: {values: [['key', '8A']]}},
    energy: {automatic: {values: [['valence', 0.83], ['arousal', 0.62]], provenance: [[ENERGY_MODEL, '1']]}},
  }});
  assert.deepEqual(detail.metadata.keyFacts, [
    {text: '122.4 BPM', source: 'analysis (raw)'},
    {text: 'Key 9A', source: 'manual override'},
    {text: 'Valence 0.8', source: 'Emomusic native regression scale'},
    {text: 'Arousal 0.6', source: 'Emomusic native regression scale'},
    {text: '3:45', source: 'audio file'}]);
  assert.deepEqual(detail.metadata.lines, ['Title: Song']);
  assert.deepEqual(trackDetailViewModel({metadata: {duration_seconds: 3725}, fields: {}}).metadata.keyFacts,
    [{text: '1:02:05', source: 'audio file'}]);
  assert.deepEqual(trackDetailViewModel({fields: {bpm: {automatic: {}}}}).metadata.keyFacts, [], 'nothing known, nothing claimed');
});

test('fields without usable evidence gather in one Not available line, each keeping its reason (#236)', () => {
  const detail = trackDetailViewModel({fields: {
    bpm: {automatic: {values: [['bpm', 120]]}},
    genres: {automatic: {values: [], provenance: []}, missing_reason: 'not analysed'},
    mood: {automatic: {values: [['calm', 0.05]], provenance: [[MOOD_MODEL, '1']]}},
    instruments: {automatic: {}, missing_reason: 'instruments: missing result'},
    key: {manual_text: 'A', automatic: {}},
  }});
  assert.deepEqual(detail.fields.map(field => field.name), ['bpm', 'mood', 'key'], 'weak scores and overrides are evidence');
  assert.deepEqual(detail.unavailable, {summary: 'Not available: genres, instruments', reasons: [
    {name: 'genres', text: 'no usable evidence (unsupported or missing model/scale); not analysed'},
    {name: 'instruments', text: 'no usable evidence (unsupported or missing model/scale); instruments: missing result'}]});
  assert.equal(trackDetailViewModel({fields: {bpm: {automatic: {values: [['bpm', 120]]}}}}).unavailable, null);
});
