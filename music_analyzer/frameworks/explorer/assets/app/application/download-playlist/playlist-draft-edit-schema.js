// The schemas of edits to the playlist draft (#146, #137): the request models the controls send.

import {ARC_SHAPES} from '../../domain/energy-arc-chain.js';
import {ARC_LENGTH_UNITS} from '../../domain/playlist-draft.js';

export const PLAYLIST_DRAFT_EDIT = Object.freeze({
  subject: 'playlist control',
  fields: Object.freeze({
    bpmMin: Object.freeze({kind: 'number-text', label: 'Min BPM'}),
    bpmMax: Object.freeze({kind: 'number-text', label: 'Max BPM'}),
    count: Object.freeze({kind: 'number-text', label: 'Track count'}),
    durationMinutes: Object.freeze({kind: 'number-text', label: 'Duration'}),
    harmonicMixing: Object.freeze({kind: 'switch', label: 'Harmonic mixing'}),
    minimumKeyStrength: Object.freeze({kind: 'number-text', label: 'Min key strength'}),
    arcLengthUnit: Object.freeze({kind: 'choice', label: 'Arc length unit', choices: ARC_LENGTH_UNITS}),
    moodHold: Object.freeze({kind: 'text', label: 'Mood hold'}),
  }),
});

export const ENERGY_ARC_EDIT = Object.freeze({
  subject: 'energy arc field',
  fields: Object.freeze({
    shape: Object.freeze({kind: 'choice', label: 'Arc shape', choices: ARC_SHAPES}),
    length: Object.freeze({kind: 'number-text', label: 'Arc length'}),
    low: Object.freeze({kind: 'number-text', label: 'Arc energy low'}),
    high: Object.freeze({kind: 'number-text', label: 'Arc energy high'}),
  }),
});
