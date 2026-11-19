// The schema of an edit to the playlist draft (#146): the request model the controls send.

import {ENERGY_ARC_SHAPES} from '../../domain/playlist-draft.js';

export const PLAYLIST_DRAFT_EDIT = Object.freeze({
  subject: 'playlist control',
  fields: Object.freeze({
    bpmMin: Object.freeze({kind: 'number-text', label: 'Min BPM'}),
    bpmMax: Object.freeze({kind: 'number-text', label: 'Max BPM'}),
    count: Object.freeze({kind: 'number-text', label: 'Track count'}),
    durationMinutes: Object.freeze({kind: 'number-text', label: 'Duration'}),
    harmonicMixing: Object.freeze({kind: 'switch', label: 'Harmonic mixing'}),
    minimumKeyStrength: Object.freeze({kind: 'number-text', label: 'Min key strength'}),
    energyArc: Object.freeze({kind: 'choice', label: 'Energy arc', choices: ENERGY_ARC_SHAPES}),
    energyLow: Object.freeze({kind: 'number-text', label: 'Energy low'}),
    energyHigh: Object.freeze({kind: 'number-text', label: 'Energy high'}),
    moodHold: Object.freeze({kind: 'text', label: 'Mood hold'}),
  }),
});
