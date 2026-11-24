// Issue #243: the track-labels response, checked against its schema at the boundary.
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {trackLabelsFrom} from '../../../../../music_explorer/frameworks/explorer/assets/app/adapters/gateways/track-labels-dto.js';

test('each label names its track, title and artist', () => {
  assert.deepEqual(trackLabelsFrom({labels: [{track_id: 'a', title: 'Alpha', artist: 'Synthetic'}]}),
    [{trackId: 'a', title: 'Alpha', artist: 'Synthetic'}]);
});

test('a wrong shape is refused whole, with a message saying what is wrong', () => {
  assert.throws(() => trackLabelsFrom({}), /labels must be a list/);
  assert.throws(() => trackLabelsFrom({labels: [{track_id: 'a', title: 7, artist: 'x'}]}), /label 1 title must be text/);
  assert.throws(() => trackLabelsFrom({labels: [null]}), /label 1 track_id must be text/);
});
