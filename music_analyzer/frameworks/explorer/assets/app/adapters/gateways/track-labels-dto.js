// The track-labels response (#243), checked against its schema at the boundary. A wrong shape is refused whole.

export function trackLabelsFrom(body) {
  if (!Array.isArray(body?.labels)) refuseTrackLabels('labels must be a list');
  return body.labels.map(trackLabelFrom);
}

function trackLabelFrom(label, index) {
  const name = `label ${index + 1}`;
  for (const field of ['track_id', 'title', 'artist']) {
    if (typeof label?.[field] !== 'string') refuseTrackLabels(`${name} ${field} must be text`);
  }
  return {trackId: label.track_id, title: label.title, artist: label.artist};
}

function refuseTrackLabels(problem) {
  throw new Error(`Invalid track labels: ${problem}`);
}
