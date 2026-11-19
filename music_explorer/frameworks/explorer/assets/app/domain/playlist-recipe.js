// The playlist a listener asks for (#146): what the Download M3U controls describe.
// Values stay as entered; the server validates them and owns their messages.

const DEFAULT_TRACK_COUNT = '10';
const DEFAULT_MINIMUM_KEY_STRENGTH = '0.5';

export function playlistRecipe({startTrackId, bpmMin, bpmMax, count, durationMinutes, harmonicMixing = true,
  minimumKeyStrength, energyArc, energyLow, energyHigh, moodHold}) {
  if (!startTrackId) throw new Error('Select a start track before downloading M3U');
  return Object.freeze({
    startTrackId,
    bpmMin: bpmMin || '',
    bpmMax: bpmMax || '',
    length: Object.freeze(playlistLength(count, durationMinutes)),
    harmonicMixing: harmonicMixing !== false,
    minimumKeyStrength: harmonicMixing === false ? null : (entered(minimumKeyStrength) || DEFAULT_MINIMUM_KEY_STRENGTH),
    energyArc: energyArcOf(energyArc, energyLow, energyHigh),
    moodHold: moodHold || null,
  });
}

function playlistLength(count, durationMinutes) {
  const minutes = entered(durationMinutes);
  return minutes ? {durationMinutes: minutes} : {count: count || DEFAULT_TRACK_COUNT};
}

function energyArcOf(shape, low, high) {
  if (!shape || shape === 'none') return null;
  return Object.freeze({shape, low: entered(low), high: entered(high)});
}

function entered(value) {
  return String(value ?? '').trim() || null;
}
