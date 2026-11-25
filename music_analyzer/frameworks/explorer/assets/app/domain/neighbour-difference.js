// How a neighbour differs from the selected track (#271, #273): on valence, arousal and BPM, the difference as a share of
// the library's span on that axis, so the three axes compare on one scale. A neighbour above the selected track is positive.

const DIFFERENCE_AXES = Object.freeze(['valence', 'arousal', 'bpm']);

export function axisSpans(tracks) {
  return Object.fromEntries(DIFFERENCE_AXES.map(axis => [axis, axisSpan(tracks.map(track => track[axis]))]));
}

export function differenceShares(selected, neighbour, spans) {
  return Object.fromEntries(DIFFERENCE_AXES.map(axis => [axis, differenceShare(selected[axis], neighbour[axis], spans[axis])]));
}

function axisSpan(values) {
  const finite = values.filter(Number.isFinite);
  return finite.length < 2 ? 0 : Math.max(...finite) - Math.min(...finite);
}

function differenceShare(from, to, span) {
  if (!(span > 0) || !Number.isFinite(from) || !Number.isFinite(to)) return 0;
  return Math.max(-1, Math.min(1, (to - from) / span));
}
