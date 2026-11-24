// The playlist preview response (#138), checked against its schema at the boundary and renamed for the use case.
// A preview shaped wrongly is refused whole, never half-read.

const TRACK_FIELDS = Object.freeze([
  ['track_id', 'trackId', 'text'], ['title', 'title', 'text'], ['artist', 'artist', 'text'], ['bpm', 'bpm', 'number'],
  ['key', 'key', 'optionalText'], ['camelot', 'camelot', 'optionalText'], ['arousal', 'arousal', 'optionalNumber'],
  ['energy_level', 'energyLevel', 'optionalNumber'], ['energy_target', 'energyTarget', 'optionalNumber'],
  ['duration_seconds', 'durationSeconds', 'optionalNumber'],
]);
const TRANSITION_FIELDS = Object.freeze([
  ['from_track_id', 'fromTrackId', 'text'], ['to_track_id', 'toTrackId', 'text'],
  ['key_compatible', 'keyCompatible', 'optionalFlag'], ['bpm_step_smooth', 'bpmStepSmooth', 'optionalFlag'],
  ['bpm_change', 'bpmChange', 'optionalNumber'],
]);
const KINDS = Object.freeze({
  text: [value => typeof value === 'string', 'must be text'],
  number: [value => Number.isFinite(value), 'must be a number'],
  optionalText: [value => value === null || typeof value === 'string', 'must be text or null'],
  optionalNumber: [value => value === null || Number.isFinite(value), 'must be a number or null'],
  optionalFlag: [value => value === null || typeof value === 'boolean', 'must be true, false or null'],
  flag: [value => typeof value === 'boolean', 'must be true or false'],
});

export function playlistPreviewFrom(body) {
  return {
    tracks: rows(body?.tracks, 'tracks', 'track', TRACK_FIELDS),
    transitions: rows(body?.transitions, 'transitions', 'transition', TRANSITION_FIELDS),
    complete: checked(body.complete, 'flag', 'complete'),
    warning: checked(body.warning, 'optionalText', 'warning'),
  };
}

function rows(list, name, noun, fields) {
  if (!Array.isArray(list)) refuse(`${name} must be a list`);
  return list.map((row, index) => Object.fromEntries(fields.map(([field, renamed, kind]) =>
    [renamed, checked(row?.[field], kind, `${noun} ${index + 1} ${field}`)])));
}

function checked(value, kind, label) {
  const [valid, rule] = KINDS[kind];
  if (!valid(value)) refuse(`${label} ${rule}`);
  return value;
}

function refuse(problem) {
  throw new Error(`Invalid playlist preview: ${problem}`);
}
