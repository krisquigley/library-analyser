// Issue #146: which of a track's retained evidence can be shown, and how it is ordered.
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {energyEvidence, fieldValues, measuredValue, scoreEvidence} from '../../../../music_explorer/frameworks/explorer/assets/app/domain/track-evidence.js';

const MOOD_MODEL = 'mtg_jamendo_moodtheme-discogs-effnet-1';
const scored = (values, provenance = [[MOOD_MODEL, '1']]) => ({automatic: {values, provenance}});

test('a field shows its values, else its summary values, else where its value came from', () => {
  assert.deepEqual(fieldValues({automatic: {values: [['a', 1]], summary_values: [['b', 2]]}}), [['a', 1]]);
  assert.deepEqual(fieldValues({automatic: {values: [], summary_values: [['b', 2]]}}), [['b', 2]]);
  assert.equal(fieldValues({automatic: {}, effective_source: 'manual'}), 'manual');
});

test('scores count only from their own model on the sigmoid mean scale', () => {
  assert.equal(scoreEvidence('mood', scored([['happy', 0.5]], [])).usable, false);
  assert.equal(scoreEvidence('mood', scored([['happy', 0.5]], [[MOOD_MODEL, '1'], ['model', 'other']])).usable, false);
  assert.equal(scoreEvidence('mood', scored([['happy', 0.5]], [[MOOD_MODEL, '1'], ['scale', 'softmax']])).usable, false);
  assert.equal(scoreEvidence('mood', scored([['happy', 0.5]], [[MOOD_MODEL, '1'], ['scale', 'sigmoid_mean_score_0_1']])).usable, true);
  assert.equal(scoreEvidence('energy', scored([])), null);
});

test('significant scores are above 0.1 and at most 1, strongest first, then by label', () => {
  const evidence = scoreEvidence('mood', scored([['sad', 0.1], ['calm', 0.6], ['happy', 0.6], ['dark', 0.9], ['odd', 1.2], ['nan', NaN], [3, 0.5]]));
  assert.deepEqual(evidence, {usable: true, hasValues: true, scores: [['dark', 0.9], ['calm', 0.6], ['happy', 0.6]]});
  assert.deepEqual(scoreEvidence('mood', scored([])), {usable: true, hasValues: false, scores: []});
});

test('energy is valence and arousal on the Emomusic native scale', () => {
  const model = 'emomusic-msd-musicnn-2';
  assert.deepEqual(energyEvidence({automatic: {values: [['valence', 4.2], ['arousal', 'x'], ['other', 1]], provenance: [[model, '1']]}}),
    [['valence', 4.2]]);
  assert.equal(energyEvidence({automatic: {values: [['valence', 4.2]], provenance: [[model, '1'], ['scale', 'probability']]}}), null);
  assert.equal(energyEvidence({automatic: {values: [['valence', 4.2]], provenance: []}}), null);
});

test('BPM is a positive number and the key is non-blank text', () => {
  assert.deepEqual(measuredValue('bpm', {automatic: {values: [['bpm', 0], ['bpm', 122.4]]}}), ['bpm', 122.4]);
  assert.equal(measuredValue('bpm', {automatic: {values: [['bpm', -1]]}}), null);
  assert.deepEqual(measuredValue('key', {automatic: {values: [['key', ' '], ['key', 'A minor']]}}), ['key', 'A minor']);
  assert.equal(measuredValue('key', {automatic: {}}), null);
});

test('a model named explicitly in the provenance counts, as the analyzer counts it; a different one does not (#251)', () => {
  const energy = provenance => ({automatic: {values: [['valence', 0.8], ['arousal', 0.6]], provenance}});
  assert.deepEqual(energyEvidence(energy([['model', 'emomusic-msd-musicnn-2'], ['scale', 'native_valence_arousal_regression']])),
    [['valence', 0.8], ['arousal', 0.6]]);
  assert.equal(energyEvidence(energy([['model', 'some-other-model']])), null);
  assert.equal(energyEvidence(energy([['model', 'emomusic-msd-musicnn-2'], ['scale', 'sigmoid_mean_score_0_1']])), null, 'the scale still has to match');
  const mood = {automatic: {values: [['happy', 0.7]], provenance: [['model', 'mtg_jamendo_moodtheme-discogs-effnet-1']]}};
  assert.deepEqual(scoreEvidence('mood', mood).scores, [['happy', 0.7]]);
});
