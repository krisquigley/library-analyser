// The hand-built playlist's journey (#294) as its chart shows it: one lane per measure on a shared time axis, so each
// keeps its own scale (no second y-axis). A step's level is its value within its lane's range, 0 at the bottom and 1 at
// the top, or null for a gap; positions along the time axis are fractions of the playlist's length.

import {displayDuration} from '../../domain/display-duration.js';
import {displayNumber} from '../../domain/display-number.js';
import {JOURNEY_MEASURES, playlistJourney} from '../../domain/playlist-journey.js';
import {previewTrackRow} from './playlist-preview-presenter.js';

const LANE_LABELS = Object.freeze({bpm: 'BPM', key: 'Key (Camelot)', arousal: 'Arousal', valence: 'Valence'});
const CAMELOT_RANGE = Object.freeze([1, 12]);
const TICK_SECONDS = Object.freeze([30, 60, 120, 300, 600, 900, 1200, 1800, 3600]);
const MOST_TICKS = 8;
const GAP = '—';

export function playlistJourneyViewModel({trackIds, previewed}) {
  const journey = playlistJourney(trackIds, previewed?.tracks || []);
  const length = journey.lengthSeconds;
  const share = seconds => seconds / length;
  return {
    hidden: journey.stops.length < 2,
    caption: `Your playlist over ${journeyTime(length)}`
      + (journey.lengthsEstimated ? ' · lengths not known are shown as the average' : ''),
    lanes: JOURNEY_MEASURES.map(measure => journeyLane(measure, journey.measures[measure], share)),
    ticks: journeyTicks(length).map(seconds => ({at: share(seconds), text: journeyTime(seconds)})),
    stops: journey.stops.map(stop => ({from: share(stop.start), to: share(stop.end), readout: stopReadout(stop)})),
  };
}

function journeyLane(measure, steps, share) {
  const range = laneRange(measure, steps.map(step => step.value).filter(value => value !== null));
  return {
    measure, label: LANE_LABELS[measure],
    range: range ? rangeText(measure, range) : 'unknown',
    steps: steps.map(step => ({from: share(step.start), to: share(step.end),
      level: step.value === null || !range ? null : (step.value - range[0]) / (range[1] - range[0])})),
  };
}

function laneRange(measure, values) {
  if (measure === 'key') return CAMELOT_RANGE;
  if (!values.length) return null;
  const [low, high] = [Math.min(...values), Math.max(...values)];
  return low === high ? [low - 1, high + 1] : [low, high];
}

function rangeText(measure, [low, high]) {
  return measure === 'key' ? `${low}–${high}` : `${displayNumber(low)}–${displayNumber(high)}`;
}

function journeyTicks(length) {
  const step = TICK_SECONDS.find(seconds => Math.floor(length / seconds) + 1 <= MOST_TICKS) ?? TICK_SECONDS.at(-1);
  return Array.from({length: Math.floor(length / step) + 1}, (_, index) => index * step);
}

function journeyTime(seconds) {
  return displayDuration(seconds) ?? '0:00';
}

function stopReadout({track, start, end}) {
  const key = track.key ? `${track.key}${track.camelot ? ` (${track.camelot})` : ''}` : GAP;
  return [previewTrackRow(track, 0, null).track, `${journeyTime(start)}–${journeyTime(end)}`, `${shown(track.bpm)} BPM`,
    `Key ${key}`, `Arousal ${shown(track.arousal)}`, `Valence ${shown(track.valence)}`].join(' · ');
}

function shown(value) {
  return Number.isFinite(value) ? displayNumber(value) : GAP;
}
