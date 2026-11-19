// The schema of an edit to the graph controls (#146): the request model the mood tracker and filters send.

export const GRAPH_CONTROLS_EDIT = Object.freeze({
  subject: 'graph control',
  fields: Object.freeze({
    mood: Object.freeze({kind: 'text', label: 'Mood tracker score label'}),
    bpmMin: Object.freeze({kind: 'number-text', label: 'Minimum BPM'}),
    bpmMax: Object.freeze({kind: 'number-text', label: 'Maximum BPM'}),
    genres: Object.freeze({kind: 'text-list', label: 'Genres'}),
  }),
});
