// Issue #243: the labels over a selected track and its neighbours, as a lifecycle and a choice of tracks.
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {NEIGHBOURHOOD_LABEL_STATES, NeighbourhoodLabelTransitionError, labelledTrackIds, nextNeighbourhoodLabelState}
  from '../../../../music_explorer/frameworks/explorer/assets/app/domain/neighbourhood-labels.js';

const LEGAL = {
  unlabelled: {request: 'labelling', clear: 'unlabelled'},
  labelling: {request: 'labelling', succeed: 'labelled', fail: 'failed', clear: 'unlabelled'},
  labelled: {request: 'labelling', clear: 'unlabelled'},
  failed: {request: 'labelling', clear: 'unlabelled'},
};

test('every transition is in the table', () => {
  assert.deepEqual(NEIGHBOURHOOD_LABEL_STATES, Object.keys(LEGAL));
  for (const state of NEIGHBOURHOOD_LABEL_STATES) {
    for (const action of ['request', 'succeed', 'fail', 'clear']) {
      const next = LEGAL[state][action];
      if (next) assert.equal(nextNeighbourhoodLabelState(state, action), next);
      else assert.throws(() => nextNeighbourhoodLabelState(state, action), NeighbourhoodLabelTransitionError);
    }
  }
});

test('the selected track comes first, then its neighbours, up to the most one request may name', () => {
  const focus = {active: true, selectedTrackId: 's', neighbourIds: new Set(['n1', 'n2'])};
  assert.deepEqual(labelledTrackIds(focus), ['s', 'n1', 'n2']);
  assert.deepEqual(labelledTrackIds({active: false, selectedTrackId: null, neighbourIds: new Set()}), []);
  const crowded = {active: true, selectedTrackId: 's', neighbourIds: new Set(Array.from({length: 150}, (_, n) => 'n' + n))};
  assert.equal(labelledTrackIds(crowded).length, 100);
});
