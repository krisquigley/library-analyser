// The playlist a listener asks for (#146, #137): what the Download M3U controls describe.
// Values stay as entered; the server validates them and owns their messages.

const DEFAULT_TRACK_COUNT = '10';
const DEFAULT_MINIMUM_KEY_STRENGTH = '0.5';

export function playlistRecipe({startTrackId, bpmMin, bpmMax, count, durationMinutes, harmonicMixing = true,
  minimumKeyStrength, energyArcs = [], arcUnit, moodHold}) {
  if (!startTrackId) throw new Error('Select a start track before downloading M3U');
  const energyPlan = Object.freeze(energyArcs.map(energyArcOf));
  return Object.freeze({
    startTrackId,
    bpmMin: bpmMin || '',
    bpmMax: bpmMax || '',
    length: Object.freeze(playlistLength(count, durationMinutes, energyPlan, arcUnit)),
    harmonicMixing: harmonicMixing !== false,
    minimumKeyStrength: harmonicMixing === false ? null : (entered(minimumKeyStrength) || DEFAULT_MINIMUM_KEY_STRENGTH),
    energyPlan,
    moodHold: moodHold || null,
  });
}

// Arcs with lengths last as long as the playlist does; otherwise its own length applies.
function playlistLength(count, durationMinutes, energyPlan, arcUnit) {
  if (energyPlan.some(arc => arc.length)) return {arcs: arcUnit};
  const minutes = entered(durationMinutes);
  return minutes ? {durationMinutes: minutes} : {count: count || DEFAULT_TRACK_COUNT};
}

function energyArcOf({shape, low, high, length}) {
  return Object.freeze({shape, low: entered(low), high: entered(high), length: entered(length)});
}

function entered(value) {
  return String(value ?? '').trim() || null;
}
