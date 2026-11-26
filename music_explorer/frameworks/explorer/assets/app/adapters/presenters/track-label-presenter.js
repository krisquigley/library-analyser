// The labels above a selected track and its neighbours (#243): title and artist, each kept short enough to read.

const LONGEST_LABEL_PART = 30;

export function trackLabelViewModels({selectedTrackId, labels}) {
  return labels.map(label => ({trackId: label.trackId, text: trackLabelText(label), selected: label.trackId === selectedTrackId}));
}

export function trackLabelText({title, artist}) {
  return `${shortLabelPart(title)} — ${shortLabelPart(artist)}`;
}

function shortLabelPart(text) {
  return text.length > LONGEST_LABEL_PART ? text.slice(0, LONGEST_LABEL_PART) + '…' : text;
}
