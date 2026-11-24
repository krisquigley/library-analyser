// What the track detail panel shows (#146): key facts and the track's embedded metadata, then each field's evidence;
// fields without usable evidence share one line that still gives each reason (#236). Nothing is invented: a key fact
// is shown only when its evidence is, and says where it comes from.

import {displayNumber} from '../../domain/display-number.js';
import {energyEvidence, measuredValue, scoreEvidence} from '../../domain/track-evidence.js';

const BARS_SHOWN = 12;
const METADATA_LABELS = Object.freeze({title: 'Title', artist: 'Artist', album: 'Album', album_artist: 'Album artist',
  date: 'Date', year: 'Year', genre: 'Genre', composer: 'Composer', track_number: 'Track number', disc_number: 'Disc number',
  comment: 'Comment'});
const METADATA_ALIASES = Object.freeze({albumartist: 'album_artist', aalbumartist: 'album_artist', aart: 'album_artist',
  tpe2: 'album_artist', tracknumber: 'track_number', trkn: 'track_number', trck: 'track_number', discnumber: 'disc_number',
  disk: 'disc_number', tpos: 'disc_number'});

export function trackDetailViewModel(detail) {
  const fields = Object.entries(detail.fields || {});
  const missing = fields.filter(([name, field]) => !fieldHasEvidence(name, field));
  return {heading: 'Current Track',
    metadata: {...trackMetadataViewModel(detail.metadata), keyFacts: trackKeyFacts(detail)},
    fields: fields.filter(([name, field]) => fieldHasEvidence(name, field)).map(([name, field]) => detailFieldViewModel(name, field)),
    unavailable: missing.length ? unavailableEvidence(missing) : null};
}

export function trackDetailLoadingViewModel() {
  return {status: 'Loading current track detail…'};
}

export function trackDetailFailureViewModel(failure) {
  return {alert: 'Unable to load current track detail: ' + (failure && failure.message ? failure.message : String(failure))};
}

export function detailFieldViewModel(name, field) {
  if (field.manual_text != null) {
    return {name, items: [{text: `Manual override: ${field.manual_text} (${field.typed_override_status || 'unresolved'}; automatic evidence not displayed)`}]};
  }
  const items = evidenceItems(name, field);
  if (field.missing_reason) items.push({text: field.missing_reason});
  return {name, items};
}

// A raw 0–1 score as a compact bar (#236): the bar fills that share of its length; the value is shown as recorded.
export function scoreBarViewModel(label, value) {
  return {label, ariaLabel: `${label}: ${displayNumber(value)} out of 1`, valueText: displayNumber(value), fillPercent: value * 100};
}

export function trackMetadataViewModel(metadata) {
  const common = Array.isArray(metadata?.common) ? metadata.common : [];
  const tags = Array.isArray(metadata?.tags) ? metadata.tags : [];
  const seen = new Set();
  const lines = [];
  for (const [key, value] of [...common, ...tags.map(([key, values]) => [key, values || []])]) {
    const canonical = canonicalMetadataKey(key);
    const valueText = metadataValueText(value);
    if (!valueText || seen.has(canonical)) continue;
    seen.add(canonical);
    lines.push(`${METADATA_LABELS[canonical] || key}: ${valueText}`);
  }
  return {lines: lines.length ? lines : ['No embedded textual metadata found']};
}

function fieldHasEvidence(name, field) {
  if (field.manual_text != null) return true;
  const scores = scoreEvidence(name, field);
  if (scores) return scores.usable && scores.hasValues;
  if (name === 'energy') return Boolean(energyEvidence(field)?.length);
  if (name === 'bpm' || name === 'key') return measuredValue(name, field) != null;
  return false;
}

function unavailableEvidence(missing) {
  return {summary: `Not available: ${missing.map(([name]) => name).join(', ')}`,
    reasons: missing.map(([name, field]) => ({name, text: detailFieldViewModel(name, field).items.map(item => item.text).join('; ')}))};
}

const ENERGY_FACT_SOURCE = 'Emomusic native regression scale';

function trackKeyFacts({fields = {}, metadata}) {
  return [bpmFact(fields.bpm), keyFact(fields.key), ...energyFacts(fields.energy), durationFact(metadata?.duration_seconds)]
    .filter(Boolean);
}

function bpmFact(field) {
  if (!field) return null;
  if (field.manual_text != null) return {text: `${field.manual_text} BPM`, source: 'manual override'};
  const measured = measuredValue('bpm', field);
  return measured && {text: `${displayNumber(measured[1])} BPM`, source: 'analysis (raw)'};
}

function keyFact(field) {
  if (!field) return null;
  if (field.manual_text != null) return {text: `Key ${field.manual_text}`, source: 'manual override'};
  const measured = measuredValue('key', field);
  return measured && {text: `Key ${measured[1]}`, source: 'analysis'};
}

function energyFacts(field) {
  if (!field || field.manual_text != null) return [];
  return (energyEvidence(field) || []).map(([axis, value]) => ({
    text: `${axis.charAt(0).toUpperCase()}${axis.slice(1)} ${displayNumber(value)}`, source: ENERGY_FACT_SOURCE}));
}

function durationFact(seconds) {
  if (typeof seconds !== 'number' || !Number.isFinite(seconds) || seconds <= 0) return null;
  const whole = Math.round(seconds);
  const [hours, minutes, rest] = [Math.floor(whole / 3600), Math.floor(whole / 60) % 60, whole % 60];
  const pad = value => String(value).padStart(2, '0');
  return {text: hours ? `${hours}:${pad(minutes)}:${pad(rest)}` : `${minutes}:${pad(rest)}`, source: 'audio file'};
}

function evidenceItems(name, field) {
  const scores = scoreEvidence(name, field);
  if (scores) return scoreItems(scores);
  if (name === 'energy') return [{text: energyText(energyEvidence(field))}];
  if (name === 'bpm' || name === 'key') return [{text: measuredText(name, measuredValue(name, field))}];
  return [{text: 'no usable evidence (no supported display scale)'}];
}

function scoreItems({usable, hasValues, scores}) {
  if (!usable) return [{text: 'no usable evidence (unsupported or missing model/scale)'}];
  const items = [{text: 'display scores > 0.1 (raw 0–1 labelled scores; not probabilities; independent of analysis cutoff).'}];
  if (!scores.length) items.push({text: hasValues ? 'no significant values' : 'no usable evidence'});
  for (const [label, value] of scores.slice(0, BARS_SHOWN)) items.push({bar: scoreBarViewModel(label, value)});
  if (scores.length > BARS_SHOWN) items.push({text: `${scores.length - BARS_SHOWN} more significant labels not shown`});
  return items;
}

function energyText(axes) {
  if (axes == null) return 'no usable evidence (unsupported model or contradictory scale)';
  if (!axes.length) return 'no usable evidence';
  return `${axes.map(([axis, value]) => `${axis}: ${displayNumber(value)}`).join(' · ')} (Emomusic native regression scale; not a 0–1 probability)`;
}

function measuredText(name, entry) {
  if (!entry) return 'no usable evidence';
  return name === 'bpm' ? `${displayNumber(entry[1])} BPM (raw)` : entry[1];
}

function canonicalMetadataKey(key) {
  const normalized = String(key || '').trim().toLowerCase().replace(/[ -]+/g, '_');
  return METADATA_ALIASES[normalized] || normalized;
}

function metadataValueText(value) {
  return Array.isArray(value) ? value.filter(item => String(item).trim()).join('; ') : String(value == null ? '' : value).trim();
}
