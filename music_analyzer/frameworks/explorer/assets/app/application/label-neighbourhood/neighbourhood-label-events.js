// What happens while the graph labels a selected track and its neighbours (#243).

export const NEIGHBOURHOOD_LABEL_EVENT_TYPES = Object.freeze(['neighbourhood-labelling', 'neighbourhood-labelled',
  'neighbourhood-labels-failed', 'neighbourhood-labels-cleared']);

export function neighbourhoodLabelling(trackIds) {
  return Object.freeze({type: 'neighbourhood-labelling', trackIds});
}

export function neighbourhoodLabelled({selectedTrackId, labels}) {
  return Object.freeze({type: 'neighbourhood-labelled', selectedTrackId, labels});
}

export function neighbourhoodLabelsFailed(message) {
  return Object.freeze({type: 'neighbourhood-labels-failed', message});
}

export function neighbourhoodLabelsCleared() {
  return Object.freeze({type: 'neighbourhood-labels-cleared'});
}
