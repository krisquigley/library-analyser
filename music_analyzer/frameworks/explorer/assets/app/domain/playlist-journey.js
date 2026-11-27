// The hand-built playlist's journey over time (#294): each previewed track spans its length in the listener's order,
// carrying its BPM, its key as a Camelot number (1–12), its arousal and its valence. A value not known is a gap. A
// track of unknown length spans the average of the known lengths, or three minutes when none is known.

export const JOURNEY_MEASURES = Object.freeze(['bpm', 'key', 'arousal', 'valence']);

const FALLBACK_TRACK_SECONDS = 180;
const CAMELOT_CODE = /^(1[0-2]|[1-9])[AB]$/;

const MEASURE_VALUES = Object.freeze({
  bpm: track => knownNumber(track.bpm),
  key: track => camelotNumber(track.camelot),
  arousal: track => knownNumber(track.arousal),
  valence: track => knownNumber(track.valence),
});

export function playlistJourney(trackIds, previewedTracks) {
  const byId = new Map(previewedTracks.map(track => [track.trackId, track]));
  const tracks = trackIds.filter(trackId => byId.has(trackId)).map(trackId => byId.get(trackId));
  const known = tracks.map(track => knownLength(track.durationSeconds)).filter(length => length !== null);
  const fallback = known.length ? known.reduce((sum, length) => sum + length, 0) / known.length : FALLBACK_TRACK_SECONDS;
  let start = 0;
  const stops = tracks.map(track => {
    const end = start + (knownLength(track.durationSeconds) ?? fallback);
    const stop = Object.freeze({track, start, end});
    start = end;
    return stop;
  });
  return Object.freeze({
    stops: Object.freeze(stops),
    lengthSeconds: start,
    lengthsEstimated: known.length < tracks.length,
    measures: Object.freeze(Object.fromEntries(JOURNEY_MEASURES.map(measure => [measure,
      Object.freeze(stops.map(stop => Object.freeze({start: stop.start, end: stop.end, value: MEASURE_VALUES[measure](stop.track)})))]))),
  });
}

function knownNumber(value) {
  return Number.isFinite(value) ? value : null;
}

function knownLength(seconds) {
  return Number.isFinite(seconds) && seconds > 0 ? seconds : null;
}

function camelotNumber(code) {
  const match = typeof code === 'string' ? CAMELOT_CODE.exec(code) : null;
  return match ? Number(match[1]) : null;
}
