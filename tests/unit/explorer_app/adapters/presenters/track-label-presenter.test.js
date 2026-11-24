// Issue #243: the labels above the selected track and its neighbours.
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {trackLabelViewModels} from '../../../../../music_explorer/frameworks/explorer/assets/app/adapters/presenters/track-label-presenter.js';

test('each label reads title and artist, the selected one marked, and long names are shortened', () => {
  const long = 'A very long synthetic title that goes on and on';
  assert.deepEqual(trackLabelViewModels({selectedTrackId: 'a', labels: [
    {trackId: 'a', title: 'Alpha', artist: 'Synthetic'}, {trackId: 'b', title: long, artist: 'Synthetic'}]}), [
    {trackId: 'a', text: 'Alpha — Synthetic', selected: true},
    {trackId: 'b', text: 'A very long synthetic title th… — Synthetic', selected: false}]);
});
