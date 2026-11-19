// Which of a track's retained evidence can be shown (#146). The detail presents evidence;
// it is not a graph filter or an analysis threshold, and raw scores are never changed.

const SCORE_FIELD_MODELS = Object.freeze({
  genres: 'genre_discogs400-discogs-effnet-1',
  mood: 'mtg_jamendo_moodtheme-discogs-effnet-1',
  instruments: 'mtg_jamendo_instrument-discogs-effnet-1',
});
const SCORE_SCALE = 'sigmoid_mean_score_0_1';
const SIGNIFICANT_SCORE = 0.1;
const ENERGY_MODEL = 'emomusic-msd-musicnn-2';
const ENERGY_SCALE = 'native_valence_arousal_regression';
const ENERGY_AXES = Object.freeze(['valence', 'arousal']);

export function fieldValues(field) {
  const automatic = field.automatic || {};
  if (automatic.values && automatic.values.length) return automatic.values;
  if (automatic.summary_values && automatic.summary_values.length) return automatic.summary_values;
  return field.effective_source;
}

export function scoreEvidence(name, field) {
  if (!Object.hasOwn(SCORE_FIELD_MODELS, name)) return null;
  if (!fromModelOnScale(field, SCORE_FIELD_MODELS[name], SCORE_SCALE)) return {usable: false};
  const values = fieldValues(field);
  const scores = Array.isArray(values) ? values.filter(isSignificantScore).sort(strongestFirst) : [];
  return {usable: true, hasValues: Array.isArray(values) && values.length > 0, scores};
}

export function energyEvidence(field) {
  const values = fieldValues(field);
  if (!fromModelOnScale(field, ENERGY_MODEL, ENERGY_SCALE) || !Array.isArray(values)) return null;
  return values.filter(([label, value]) => ENERGY_AXES.includes(label) && isFiniteNumber(value));
}

export function measuredValue(name, field) {
  const values = fieldValues(field);
  const usable = name === 'key' ? value => typeof value === 'string' && value.trim() !== '' : value => isFiniteNumber(value) && value > 0;
  return (Array.isArray(values) && values.find(([label, value]) => label === name && usable(value))) || null;
}

function fromModelOnScale(field, model, scale) {
  const provenance = Object.fromEntries(field.automatic?.provenance || []);
  return model in provenance && (provenance.model == null || provenance.model === model)
    && (provenance.scale == null || provenance.scale === scale);
}

function isSignificantScore([label, value]) {
  return typeof label === 'string' && isFiniteNumber(value) && value > SIGNIFICANT_SCORE && value <= 1;
}

function strongestFirst(a, b) {
  return b[1] - a[1] || a[0].localeCompare(b[0]);
}

function isFiniteNumber(value) {
  return typeof value === 'number' && Number.isFinite(value);
}
