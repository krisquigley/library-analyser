// The labels above a selected track and its neighbours (#243): title and artist, each kept short enough to read.

const LONGEST_LABEL_PART = 30;

export function trackLabelViewModels({selectedTrackId, labels}) {
  return labels.map(({trackId, title, artist}) => ({trackId, text: `${shortLabelPart(title)} — ${shortLabelPart(artist)}`,
    selected: trackId === selectedTrackId}));
}

function shortLabelPart(text) {
  return text.length > LONGEST_LABEL_PART ? text.slice(0, LONGEST_LABEL_PART) + '…' : text;
}
