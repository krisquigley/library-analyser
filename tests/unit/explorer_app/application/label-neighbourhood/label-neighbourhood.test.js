// Issue #243: labelling a selected track and its neighbours, once per selection; the latest selection wins.
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {createNeighbourhoodLabels} from '../../../../../music_explorer/frameworks/explorer/assets/app/application/label-neighbourhood/label-neighbourhood.js';
import {NEIGHBOURHOOD_LABEL_EVENT_TYPES} from '../../../../../music_explorer/frameworks/explorer/assets/app/application/label-neighbourhood/neighbourhood-label-events.js';

const focusOn = (selectedTrackId, ...neighbours) => ({active: true, selectedTrackId, neighbourIds: new Set(neighbours)});
const NONE = {active: false, selectedTrackId: null, neighbourIds: new Set()};

function harness() {
  const published = [], asked = [], pending = [];
  const explorerApi = {labelTracks: trackIds => { asked.push(trackIds); return new Promise((resolve, reject) => pending.push({resolve, reject, trackIds})); }};
  const labels = createNeighbourhoodLabels({explorerApi, eventBus: {publish: event => published.push(event), subscribe() {}}});
  const answer = (index = 0) => pending[index].resolve(pending[index].trackIds.map(trackId => ({trackId, title: 'T ' + trackId, artist: 'A'})));
  return {labels, published, asked, pending, answer};
}

test('the event types are the ones the use case publishes', () => {
  assert.deepEqual(NEIGHBOURHOOD_LABEL_EVENT_TYPES, ['neighbourhood-labelling', 'neighbourhood-labelled', 'neighbourhood-labels-failed', 'neighbourhood-labels-cleared']);
});

test('a selection asks once for its tracks and publishes their labels', async () => {
  const {labels, published, asked, answer} = harness();
  const done = labels.label(focusOn('a', 'b'));
  labels.label(focusOn('a', 'b'));
  answer(); await done;
  assert.deepEqual(asked, [['a', 'b']], 'the same neighbourhood is not asked again');
  assert.deepEqual(published, [{type: 'neighbourhood-labelling', trackIds: ['a', 'b']},
    {type: 'neighbourhood-labelled', selectedTrackId: 'a', labels: [{trackId: 'a', title: 'T a', artist: 'A'}, {trackId: 'b', title: 'T b', artist: 'A'}]}]);
  assert.equal(labels.state(), 'labelled');
});

test('an answer for an earlier selection is ignored once another is asked for', async () => {
  const {labels, published, answer} = harness();
  const first = labels.label(focusOn('a', 'b'));
  const second = labels.label(focusOn('c'));
  answer(1); await second;
  answer(0); await first;
  assert.deepEqual(published.filter(event => event.type === 'neighbourhood-labelled').map(event => event.selectedTrackId), ['c']);
});

test('no selection clears the labels, and a failed request leaves the graph unlabelled with a message', async () => {
  const {labels, published, pending} = harness();
  const done = labels.label(focusOn('a'));
  pending[0].reject(new Error('busy')); await done;
  assert.deepEqual(published.at(-1), {type: 'neighbourhood-labels-failed', message: 'busy'});
  await labels.label(NONE);
  assert.deepEqual(published.at(-1), {type: 'neighbourhood-labels-cleared'});
  await labels.label(NONE);
  assert.equal(published.filter(event => event.type === 'neighbourhood-labels-cleared').length, 1, 'cleared once');
});
